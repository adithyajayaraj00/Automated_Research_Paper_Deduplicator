"""FastAPI Backend Server for RESEARCH DEDUPLICATOR
Automated Research-Paper Deduplication and Verification System

Supports:
- Separate runs with isolated directories under `runs/` (Processing History)
- Pure PDF upload workflow: no hardcoded P1-P7, any number of PDFs
- Multi-step automatic pipeline execution
- Human verification with persistent decisions per run
- Dynamic PRISMA 2020 flowchart generation (PNG and PDF) per run
- Separate Benchmark Experiment for Crossref 500
"""

import ast
import hashlib
import html
import json
import os
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import pandas as pd
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Import existing backend modules
from src.build_retained_dataset import build_retained_dataset
from src.enrich_pdf_metadata import enrich_metadata
from src.file_deduplication import find_file_duplicates
from src.metadata_quality_check import check_metadata
from src.paper_deduplication import detect_paper_duplicates
from src.pdf_ingestion import extract_pdf_metadata, ingest_pdfs
from src.preprocessing import normalize_papers
from src.prisma_flowchart import create_prisma_flowchart
from src.prisma_reporting import generate_prisma_report
from src.verification import create_verification_queue

app = FastAPI(
    title="Research Deduplicator API",
    description="Multi-run research paper deduplication system for PRISMA systematic literature reviews",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent
RUNS_DIR = BASE_DIR / "runs"
RUNS_DIR.mkdir(parents=True, exist_ok=True)
BENCHMARK_DIR = BASE_DIR / "output"
FRONTEND_DIST = BASE_DIR / "frontend" / "dist"

# Active job tracking
active_jobs = {}


def get_next_run_id() -> str:
    """Generate sequential run ID like run_001, run_002."""
    existing = [
        d.name for d in RUNS_DIR.iterdir()
        if d.is_dir() and d.name.startswith("run_")
    ]
    numbers = []
    for name in existing:
        try:
            num = int(name.split("_")[1])
            numbers.append(num)
        except (IndexError, ValueError):
            pass
    next_num = max(numbers, default=0) + 1
    return f"run_{next_num:03d}"


def get_run_dir(run_id: str) -> Path:
    r_dir = RUNS_DIR / run_id
    if not r_dir.exists():
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")
    return r_dir


def log_run_job(run_id: str, message: str):
    timestamp = time.strftime("%H:%M:%S")
    entry = f"[{timestamp}] {message}"
    if run_id in active_jobs:
        active_jobs[run_id]["logs"].append(entry)
        active_jobs[run_id]["message"] = message
    print(f"[{run_id}] {entry}")


def _clean_text(value) -> str:
    """Unescape HTML entities (e.g. &amp;) and strip markup for display."""
    import re as _re
    text = html.unescape(str(value or ""))
    return " ".join(_re.sub(r"<[^>]+>", "", text).split())


def _format_pub_date(raw) -> str:
    """Show '[[2016]]' / '[[2016, 3, 4]]' (old CSVs) as 2016 / 2016-03-04."""
    raw = str(raw or "").strip()
    if not raw:
        return ""
    try:
        parts = ast.literal_eval(raw)
        if isinstance(parts, (list, tuple)) and parts:
            if isinstance(parts[0], (list, tuple)):
                return "-".join(
                    str(x).zfill(4 if i == 0 else 2) for i, x in enumerate(parts[0])
                )
            return "-".join(
                str(x).zfill(4 if i == 0 else 2) for i, x in enumerate(parts)
            )
        elif isinstance(parts, int):
            return str(parts)
    except Exception:
        pass
    return raw


def read_run_info(run_dir: Path) -> dict:
    info_file = run_dir / "info.json"
    if info_file.exists():
        try:
            return json.loads(info_file.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def update_run_info(run_dir: Path, **updates) -> dict:
    info = read_run_info(run_dir)
    info.update(updates)
    (run_dir / "info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    return info


def _load_existing_queue_decisions(queue_csv: Path) -> dict:
    """Load existing reviewer decisions from queue CSV keyed by record_id."""
    if not queue_csv.exists():
        return {}
    try:
        df = pd.read_csv(queue_csv, dtype=str).fillna("")
        decisions = {}
        for _, row in df.iterrows():
            rid = str(row.get("record_id", ""))
            if rid:
                decisions[rid] = {
                    "verification_status": str(row.get("verification_status", "Pending")),
                    "reviewer_decision": str(row.get("reviewer_decision", "")),
                    "reviewer_note": str(row.get("reviewer_note", "")),
                    "reviewed_at": str(row.get("reviewed_at", "")),
                }
        return decisions
    except Exception:
        return {}


def rebuild_run_outputs(run_id: str) -> dict:
    """Recompute everything downstream of metadata enrichment for one run.

    Order (so nothing is counted twice):
      1. exact SHA-256 file copies are added directly to the verification queue
         with match_reason='Exact File Duplicate (SHA-256)' so humans review them.
      2. paper-level detection runs on the remaining unique files.
      3. flagged candidates go to the human queue – existing decisions are kept.
      4. retained dataset = all records minus reviewer-CONFIRMED duplicates.
      5. PRISMA summary + flowchart are regenerated from those files.

    Record IDs are derived from the file hash, so they stay the same on every
    rebuild and reviewer decisions are never orphaned.
    """
    run_dir = RUNS_DIR / run_id
    enriched_csv = run_dir / "pdf_enriched_metadata.csv"
    file_dups_csv = run_dir / "file_duplicates.csv"
    results_csv = run_dir / "deduplication_results.csv"
    queue_csv = run_dir / "verification_queue.csv"
    retained_csv = run_dir / "deduplicated_records.csv"
    summary_csv = run_dir / "prisma_summary.csv"

    enriched = pd.read_csv(enriched_csv, dtype=str).fillna("")

    # Load SHA-256 file duplicates
    file_dup_filenames = set()
    file_dup_rows = []
    file_dups_count = 0
    if file_dups_csv.exists():
        fdf = pd.read_csv(file_dups_csv, dtype=str).fillna("")
        file_dups_count = len(fdf)
        for _, frow in fdf.iterrows():
            fname = str(frow.get("filename", ""))
            file_dup_filenames.add(fname)
            file_dup_rows.append(frow)

    # Restore existing reviewer decisions (survives rebuilds)
    existing_decisions = _load_existing_queue_decisions(queue_csv)

    # Run paper-level dedup only on files that are NOT SHA-256 duplicates
    unique = enriched[~enriched["filename"].astype(str).isin(file_dup_filenames)].copy()
    unique["record_id"] = [
        "REC-" + hashlib.sha1(f"{h}|{n}".encode("utf-8")).hexdigest()[:16]
        for h, n in zip(unique.get("file_hash", unique.get("filename", "")), unique["filename"])
    ]

    results = detect_paper_duplicates(normalize_papers(unique))
    results.to_csv(results_csv, index=False)

    # Build paper-level queue (from paper dedup results)
    paper_queue = create_verification_queue(results, dataset="synthetic", queue_file=queue_csv)

    # Build SHA-256 file-dup queue entries
    sha_queue_rows = []
    if file_dup_rows:
        # Build lookup of filename -> enriched row for the "original" paper
        enriched_lookup = enriched.set_index("filename").to_dict("index") if not enriched.empty else {}
        for frow in file_dup_rows:
            dup_fname = str(frow.get("filename", ""))
            orig_fname = str(frow.get("duplicate_of_file", ""))
            file_hash = str(frow.get("file_hash", ""))

            # Generate a stable record_id for this sha-dup
            dup_record_id = "SHA-" + hashlib.sha1(
                f"{file_hash}|{dup_fname}".encode("utf-8")
            ).hexdigest()[:16]

            # Get original paper's record_id from results (it went through paper-level dedup)
            orig_rid = ""
            if not results.empty and "filename" in results.columns and "record_id" in results.columns:
                orig_mask = results["filename"].astype(str) == orig_fname
                if orig_mask.any():
                    orig_rid = str(results.loc[orig_mask, "record_id"].iloc[0])

            # Get metadata from enriched CSV for the duplicate file
            dup_meta = enriched_lookup.get(dup_fname, {})
            orig_meta = enriched_lookup.get(orig_fname, {})

            sha_row = {
                "record_id": dup_record_id,
                "filename": dup_fname,
                "file_path": str(frow.get("file_path", "")),
                "source": str(frow.get("source", "")),
                "file_hash": file_hash,
                "title": str(dup_meta.get("title", "")),
                "author": str(dup_meta.get("author", "")),
                "doi": str(dup_meta.get("doi", "")),
                "year": str(dup_meta.get("year", "")),
                "crossref_journal": str(dup_meta.get("crossref_journal", "")),
                "crossref_publisher": str(dup_meta.get("crossref_publisher", "")),
                "duplicate_status": "Exact File Duplicate",
                "matched_record": orig_rid,
                "title_similarity": 100.0,
                "match_reason": "Exact File Duplicate (SHA-256)",
                "verification_status": "Pending",
                "reviewer_decision": "",
                "reviewer_note": "",
                "reviewed_at": "",
            }
            sha_queue_rows.append(sha_row)

    # Merge sha-dup rows + paper-level queue rows
    if sha_queue_rows:
        sha_df = pd.DataFrame(sha_queue_rows)
        if paper_queue is not None and not paper_queue.empty:
            combined_queue = pd.concat([sha_df, paper_queue], ignore_index=True)
        else:
            combined_queue = sha_df
    elif paper_queue is not None and not paper_queue.empty:
        combined_queue = paper_queue
    else:
        combined_queue = pd.DataFrame()

    # Restore existing decisions by record_id
    if not combined_queue.empty and existing_decisions:
        for col in ("verification_status", "reviewer_decision", "reviewer_note", "reviewed_at"):
            if col not in combined_queue.columns:
                combined_queue[col] = ""
        for i, row in combined_queue.iterrows():
            rid = str(row.get("record_id", ""))
            if rid in existing_decisions:
                prev = existing_decisions[rid]
                combined_queue.at[i, "verification_status"] = prev.get("verification_status", "Pending")
                combined_queue.at[i, "reviewer_decision"] = prev.get("reviewer_decision", "")
                combined_queue.at[i, "reviewer_note"] = prev.get("reviewer_note", "")
                combined_queue.at[i, "reviewed_at"] = prev.get("reviewed_at", "")

    # Save queue
    combined_queue.to_csv(queue_csv, index=False) if not combined_queue.empty else pd.DataFrame().to_csv(queue_csv, index=False)

    # Collect confirmed record_ids from PAPER-LEVEL queue only (records in results).
    # SHA-256 dup records (SHA- prefix) are never in `results`, so they
    # don't need to be subtracted from retained separately.
    paper_confirmed_ids = set()
    if not combined_queue.empty and "verification_status" in combined_queue.columns:
        paper_queue_mask = ~combined_queue["record_id"].astype(str).str.startswith("SHA-")
        paper_queue_only = combined_queue[paper_queue_mask]
        paper_confirmed_ids = set(
            paper_queue_only.loc[
                paper_queue_only["verification_status"] == "Confirmed Duplicate", "record_id"
            ]
        )

    # Build retained: all records from results EXCEPT confirmed paper-level dups.
    # SHA-256 confirmed dups are already excluded from `results` (they were in file_dup_filenames).
    results[~results["record_id"].isin(paper_confirmed_ids)].to_csv(retained_csv, index=False)

    generate_prisma_report(
        dataset="run",
        results_file=results_csv,
        queue_file=queue_csv,
        retained_file=retained_csv,
        report_file=summary_csv,
        file_duplicates_count=file_dups_count,
    )

    info = read_run_info(run_dir)
    create_prisma_flowchart(
        summary_file=summary_csv,
        retained_file=retained_csv,
        png_file=run_dir / "prisma_flowchart.png",
        pdf_file=run_dir / "prisma_flowchart.pdf",
        title_text=f"PRISMA 2020 Flow Diagram \u2013 {info.get('name', run_id)}",
    )

    total_queue = len(combined_queue) if not combined_queue.empty else 0
    pending = 0
    if not combined_queue.empty and "verification_status" in combined_queue.columns:
        pending = int(
            (~combined_queue["verification_status"].isin(["Confirmed Duplicate", "Not Duplicate"])).sum()
        )

    info = read_run_info(run_dir)
    info["status"] = "completed"
    info.pop("error", None)
    info.update({
        "has_candidates": total_queue > 0,
        "candidates_count": total_queue,
        "file_duplicates": file_dups_count,
        "pending_review": pending,
    })
    (run_dir / "info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    active_jobs.pop(run_id, None) if active_jobs.get(run_id, {}).get("status") == "error" else None
    return {
        "file_duplicates": file_dups_count,
        "records_compared": len(results),
        "candidates": total_queue,
        "pending": pending,
        "retained": len(results) - len(paper_confirmed_ids),
    }



def run_pipeline_for_run(run_id: str, file_names: List[str]):
    """Execute the full deduplication pipeline for an isolated run."""
    run_dir = RUNS_DIR / run_id
    pdf_dir = run_dir / "pdfs"
    extracted_csv = run_dir / "pdf_extracted_metadata.csv"
    enriched_csv = run_dir / "pdf_enriched_metadata.csv"
    issues_csv = run_dir / "pdf_metadata_enrichment_issues.csv"
    review_csv = run_dir / "pdf_metadata_review.csv"
    file_dups_csv = run_dir / "file_duplicates.csv"
    results_csv = run_dir / "deduplication_results.csv"
    queue_csv = run_dir / "verification_queue.csv"
    retained_csv = run_dir / "deduplicated_records.csv"
    prisma_summary_csv = run_dir / "prisma_summary.csv"
    flowchart_png = run_dir / "prisma_flowchart.png"
    flowchart_pdf = run_dir / "prisma_flowchart.pdf"
    info_json = run_dir / "info.json"

    job = active_jobs.get(run_id)

    try:
        job["status"] = "running"
        job["started_at"] = time.time()
        job["progress"] = 10
        job["step"] = "PDF Ingestion"
        log_run_job(run_id, f"Saved {len(file_names)} uploaded PDF file(s). Starting PyMuPDF text & SHA-256 extraction...")

        # Step 1: PDF Ingestion
        ingest_pdfs(pdf_dir=pdf_dir, output_file=extracted_csv)
        job["progress"] = 30
        log_run_job(run_id, "PDF text, author, DOI, and SHA-256 hashes successfully extracted.")
        time.sleep(0.4)

        # Step 2: Metadata Enrichment
        job["step"] = "Crossref Metadata Enrichment"
        job["progress"] = 50
        log_run_job(run_id, "Querying Crossref REST API for bibliographic enrichment & title validation...")
        enrich_metadata(input_file=extracted_csv, output_file=enriched_csv, issues_file=issues_csv)
        check_metadata(input_file=enriched_csv, output_file=review_csv)
        job["progress"] = 65
        log_run_job(run_id, "Crossref enrichment and metadata quality inspection completed.")
        time.sleep(0.4)

        # Step 3: File-level Deduplication
        job["step"] = "File-Level Deduplication (SHA-256)"
        job["progress"] = 75
        log_run_job(run_id, "Evaluating exact binary file copies using SHA-256 digests...")
        file_dups = find_file_duplicates(metadata_csv=extracted_csv)
        file_dups.to_csv(file_dups_csv, index=False)
        log_run_job(run_id, f"Found {len(file_dups)} exact file-level duplicate(s).")
        time.sleep(0.4)

        # Steps 4-6: paper-level detection on UNIQUE files, queue, retained, PRISMA
        job["step"] = "Paper-Level Deduplication"
        job["progress"] = 85
        log_run_job(run_id, "Excluding exact file copies, then running DOI, title and fuzzy matching on unique files...")
        outcome = rebuild_run_outputs(run_id)
        queue = pd.read_csv(queue_csv) if queue_csv.exists() else pd.DataFrame()
        job["progress"] = 98
        log_run_job(
            run_id,
            f"{outcome['records_compared']} unique record(s) compared; "
            f"{outcome['candidates']} candidate(s) queued for human verification.",
        )

        job["progress"] = 100
        job["status"] = "completed"
        job["completed_at"] = time.time()
        job["step"] = "Completed"
        log_run_job(run_id, f"Processing finished. {len(queue)} candidates queued for human verification.")

        # Update info.json
        run_info = {
            "run_id": run_id,
            "name": job.get("name", run_id),
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "pdf_count": len(file_names),
            "status": "completed",
            "has_candidates": len(queue) > 0,
            "candidates_count": len(queue),
            "file_duplicates": outcome["file_duplicates"],
            "pending_review": outcome["pending"],
        }
        with open(info_json, "w", encoding="utf-8") as f:
            json.dump(run_info, f, indent=2)

    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)
        log_run_job(run_id, f"Processing error: {e}")
        run_info = {
            "run_id": run_id,
            "name": job.get("name", run_id),
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "pdf_count": len(file_names),
            "status": "error",
            "error": str(e),
        }
        with open(info_json, "w", encoding="utf-8") as f:
            json.dump(run_info, f, indent=2)


# ==============================================================================
# API Endpoints
# ==============================================================================

@app.get("/api/health")
def health_check():
    return {"status": "ok", "app": "RESEARCH DEDUPLICATOR", "version": "2.0.0"}


@app.get("/api/runs")
def list_runs():
    """List all available processing runs, sorted newest first."""
    runs = []
    if RUNS_DIR.exists():
        for d in sorted(RUNS_DIR.iterdir(), reverse=True):
            if d.is_dir() and d.name.startswith("run_"):
                info_file = d / "info.json"
                if info_file.exists():
                    try:
                        with open(info_file, "r", encoding="utf-8") as f:
                            runs.append(json.load(f))
                        continue
                    except Exception:
                        pass
                # Fallback if info.json missing
                runs.append({
                    "run_id": d.name,
                    "name": d.name.replace("_", " ").title(),
                    "created_at": datetime.fromtimestamp(d.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                    "pdf_count": len(list((d / "pdfs").glob("*.pdf"))) if (d / "pdfs").exists() else 0,
                    "status": "completed" if (d / "prisma_summary.csv").exists() else "pending",
                })
    return {"runs": runs}


@app.delete("/api/runs/{run_id}")
def delete_run(run_id: str):
    """Permanently delete a run and all its associated files."""
    run_dir = RUNS_DIR / run_id
    if not run_dir.exists() or not run_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")
    if not run_id.startswith("run_"):
        raise HTTPException(status_code=400, detail="Invalid run ID format.")
    try:
        # Remove from active jobs if running
        active_jobs.pop(run_id, None)
        shutil.rmtree(run_dir)
        return {"status": "deleted", "run_id": run_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete run: {e}")


@app.post("/api/upload")
async def create_run_and_upload_pdfs(files: List[UploadFile] = File(...)):
    """Upload PDFs to a new isolated run directory and trigger background pipeline."""
    if not files:
        raise HTTPException(status_code=400, detail="No files provided.")

    run_id = get_next_run_id()
    run_dir = RUNS_DIR / run_id
    pdf_dir = run_dir / "pdfs"
    pdf_dir.mkdir(parents=True, exist_ok=True)

    saved_filenames = []
    for file in files:
        if not file.filename.lower().endswith(".pdf"):
            continue
        dest = pdf_dir / file.filename
        with dest.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        saved_filenames.append(file.filename)

    if not saved_filenames:
        raise HTTPException(status_code=400, detail="No valid PDF files were uploaded.")

    # Format run name e.g. "Run 001 – 8 Research Papers"
    run_num = run_id.split("_")[1]
    run_name = f"Run {run_num} – {len(saved_filenames)} Research Papers"

    active_jobs[run_id] = {
        "run_id": run_id,
        "name": run_name,
        "status": "queued",
        "step": "Initializing",
        "progress": 5,
        "message": f"Queued {len(saved_filenames)} PDF file(s).",
        "logs": [],
        "started_at": time.time(),
        "completed_at": None,
        "error": None,
    }

    thread = threading.Thread(target=run_pipeline_for_run, args=(run_id, saved_filenames))
    thread.daemon = True
    thread.start()

    return {
        "status": "started",
        "run_id": run_id,
        "name": run_name,
        "file_count": len(saved_filenames),
        "files": saved_filenames,
    }


@app.get("/api/runs/{run_id}/status")
def get_run_status(run_id: str):
    """Get live job progress or completion status for a run."""
    if run_id in active_jobs:
        return active_jobs[run_id]

    run_dir = get_run_dir(run_id)
    summary_csv = run_dir / "prisma_summary.csv"
    return {
        "run_id": run_id,
        "status": "completed" if summary_csv.exists() else "idle",
        "step": "Completed" if summary_csv.exists() else "Idle",
        "progress": 100 if summary_csv.exists() else 0,
        "message": "Ready.",
        "logs": [],
    }


@app.get("/api/runs/{run_id}/results")
def get_run_results(run_id: str):
    """Get the processing results summary for a specific run."""
    run_dir = get_run_dir(run_id)
    pdf_dir = run_dir / "pdfs"
    extracted_csv = run_dir / "pdf_extracted_metadata.csv"
    results_csv = run_dir / "deduplication_results.csv"
    queue_csv = run_dir / "verification_queue.csv"
    retained_csv = run_dir / "deduplicated_records.csv"
    file_dups_csv = run_dir / "file_duplicates.csv"
    flowchart_png = run_dir / "prisma_flowchart.png"

    info = read_run_info(run_dir)
    job = active_jobs.get(run_id, {})
    pipeline_status = job.get("status") or info.get("status") or "unknown"
    pipeline_error = job.get("error") or info.get("error") or ""

    pdf_files = list(pdf_dir.glob("*.pdf")) if pdf_dir.exists() else []
    total_uploaded = len(pdf_files)

    # Exact file duplicates (SHA-256)
    file_dups_count = 0
    file_dups_list = []
    if file_dups_csv.exists():
        fdf = pd.read_csv(file_dups_csv).fillna("")
        file_dups_count = len(fdf)
        for _, r in fdf.iterrows():
            file_dups_list.append({
                "duplicate": str(r.get("filename", "")),
                "original": str(r.get("duplicate_of_file", "")),
                "hash": str(r.get("file_hash", "")),
            })

    # Paper-level candidates = the rows that actually went to the queue
    queue_ready = queue_csv.exists()
    confirmed_count = not_duplicate_count = pending_count = 0
    paper_candidates_count = 0
    if queue_ready:
        qdf = pd.read_csv(queue_csv).fillna("")
        paper_candidates_count = len(qdf)
        if "verification_status" in qdf.columns and len(qdf):
            confirmed_count = int((qdf["verification_status"] == "Confirmed Duplicate").sum())
            not_duplicate_count = int((qdf["verification_status"] == "Not Duplicate").sum())
            pending_count = int((~qdf["verification_status"].isin(
                ["Confirmed Duplicate", "Not Duplicate"])).sum())

    # Retained count comes ONLY from the retained file - never guessed.
    unique_retained_count = None
    if retained_csv.exists():
        unique_retained_count = len(pd.read_csv(retained_csv))

    if not queue_ready:
        review_stage = "Not started"
    elif paper_candidates_count == 0:
        review_stage = "No candidates"
    elif pending_count == 0:
        review_stage = "Reviewed"
    else:
        review_stage = f"{pending_count} Pending"

    if pipeline_status == "error":
        prisma_stage = "Failed"
    elif flowchart_png.exists():
        prisma_stage = "Generated"
    else:
        prisma_stage = "Pending"

    stages = [
        {"name": "PDF Ingestion & SHA-256 Hashing", "status": "Completed" if extracted_csv.exists() else "Pending"},
        {"name": "Crossref Metadata Enrichment", "status": "Completed" if (run_dir / "pdf_enriched_metadata.csv").exists() else "Pending"},
        {"name": "File-Level Duplicate Detection", "status": "Completed" if file_dups_csv.exists() else "Pending"},
        {"name": "Paper-Level Duplicate Detection", "status": "Completed" if results_csv.exists() else "Pending"},
        {"name": "Human Verification Queue", "status": review_stage},
        {"name": "PRISMA Flowchart & Reporting", "status": prisma_stage},
    ]

    return {
        "run_id": run_id,
        "pipeline_status": pipeline_status,
        "pipeline_error": pipeline_error,
        "total_uploaded": total_uploaded,
        "exact_file_duplicates": file_dups_count,
        "file_duplicates_list": file_dups_list,
        "paper_duplicate_candidates": paper_candidates_count,
        "confirmed_duplicates_removed": confirmed_count,
        "not_duplicate_retained": not_duplicate_count,
        "pending_verification": pending_count,
        "unique_retained_records": unique_retained_count,
        "queue_ready": queue_ready,
        "stages": stages,
        "ready_for_finalization": queue_ready and pending_count == 0,
    }


def _load_metadata_reviews(run_dir: Path) -> dict:
    path = run_dir / "metadata_reviews.csv"
    if not path.exists():
        return {}
    df = pd.read_csv(path).fillna("")
    return {str(r["filename"]): r.to_dict() for _, r in df.iterrows()}


@app.get("/api/runs/{run_id}/metadata")
def get_run_metadata(
    run_id: str,
    q: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
):
    """Return extracted & enriched metadata for a run."""
    run_dir = get_run_dir(run_id)
    enriched_csv = run_dir / "pdf_enriched_metadata.csv"
    extracted_csv = run_dir / "pdf_extracted_metadata.csv"

    if not enriched_csv.exists() and not extracted_csv.exists():
        return {"records": [], "total": 0, "awaiting_review": 0}

    csv_path = enriched_csv if enriched_csv.exists() else extracted_csv
    try:
        df = pd.read_csv(csv_path, dtype=str, encoding="utf-8").fillna("")
    except UnicodeDecodeError:
        df = pd.read_csv(csv_path, dtype=str, encoding="latin-1").fillna("")

    issues_csv = run_dir / "pdf_metadata_enrichment_issues.csv"
    issues_map = {}
    if issues_csv.exists():
        try:
            idf = pd.read_csv(issues_csv, dtype=str).fillna("")
            for _, r in idf.iterrows():
                issues_map[str(r.get("filename", ""))] = str(r.get("issue", ""))
        except Exception:
            pass

    reviews = _load_metadata_reviews(run_dir)

    records = []
    for _, row in df.iterrows():
        try:
            fname = str(row.get("filename", ""))
            validation = str(row.get("metadata_validation", "Needs Review"))
            needs_review = not validation.lower().startswith(("title match", "manually"))
            review = reviews.get(fname, {})
            review_status = review.get("decision") or ("Pending" if needs_review else "Not required")

            records.append({
                "filename": fname,
                "title": _clean_text(row.get("title", "")),
                "author": _clean_text(row.get("author", "")),
                "doi": str(row.get("doi", "")),
                "year": str(row.get("year", "")),
                "journal": _clean_text(row.get("crossref_journal", "")),
                "publisher": _clean_text(row.get("crossref_publisher", "")),
                "volume": str(row.get("crossref_volume", "")),
                "issue": str(row.get("crossref_issue", "")),
                "validation_note": issues_map.get(fname, ""),
                "page": str(row.get("crossref_page", "")),
                "publication_date": _format_pub_date(row.get("crossref_publication_date", "")),
                "metadata_source": str(row.get("metadata_source", "PDF extraction")),
                "validation_status": validation,
                "enrichment_status": str(row.get("enrichment_status", "")),
                "title_match_score": str(row.get("title_match_score", "")),
                "file_hash": str(row.get("file_hash", "")),
                "needs_review": needs_review,
                "review_status": review_status,
                "review_note": str(review.get("note", "")),
                "reviewed_at": str(review.get("reviewed_at", "")),
                # Side-by-side fields
                "pdf_title": _clean_text(row.get("pdf_title", row.get("title", ""))),
                "pdf_author": _clean_text(row.get("pdf_author", row.get("author", ""))),
                "pdf_year": str(row.get("pdf_year", row.get("year", ""))),
                "pdf_doi": str(row.get("doi", "")),
                "crossref_title": _clean_text(row.get("crossref_title", "")),
                "crossref_author": _clean_text(row.get("crossref_author", "")),
                "crossref_doi": str(row.get("crossref_doi", "")),
                "crossref_year": str(row.get("crossref_year", "")),
            })
        except Exception as row_err:
            print(f"[metadata] Error processing row for {row.get('filename', '?')}: {row_err}")
            continue

    awaiting = sum(1 for r in records if r["needs_review"] and r["review_status"] == "Pending")
    total_unfiltered = len(records)

    if q:
        ql = q.lower()
        records = [
            r for r in records
            if ql in r["title"].lower() or ql in r["author"].lower()
            or ql in r["doi"].lower() or ql in r["filename"].lower()
        ]

    if status and status != "all":
        if status.lower() == "awaiting review":
            records = [r for r in records if r["needs_review"] and r["review_status"] == "Pending"]
        else:
            records = [r for r in records if r["validation_status"].lower().startswith(status.lower())]

    return {"records": records, "total": len(records), "total_unfiltered": total_unfiltered, "awaiting_review": awaiting}


class MetadataReviewRequest(BaseModel):
    filename: str
    decision: str  # "Accepted" | "Rejected"
    note: Optional[str] = ""


@app.post("/api/runs/{run_id}/metadata/review")
def submit_metadata_review(run_id: str, req: MetadataReviewRequest):
    """Save the reviewer's decision on a Crossref match that needed review.

    Accepted -> the Crossref title/authors/year/DOI become the record's metadata.
    Rejected -> the PDF-extracted values are kept.
    Paper-level detection is then rebuilt; earlier duplicate decisions are kept.
    """
    if req.decision not in {"Accepted", "Rejected"}:
        raise HTTPException(status_code=400, detail="decision must be 'Accepted' or 'Rejected'.")

    run_dir = get_run_dir(run_id)
    enriched_csv = run_dir / "pdf_enriched_metadata.csv"
    if not enriched_csv.exists():
        raise HTTPException(status_code=404, detail="Enriched metadata not found.")

    df = pd.read_csv(enriched_csv, dtype=str).fillna("")
    mask = df["filename"].astype(str) == req.filename
    if not mask.any():
        raise HTTPException(status_code=404, detail=f"File '{req.filename}' not found in this run.")

    if req.decision == "Accepted":
        if not str(df.loc[mask, "crossref_title"].iloc[0]).strip():
            raise HTTPException(status_code=400, detail="There is no Crossref record to accept for this file.")
        for target, source in (("title", "crossref_title"), ("author", "crossref_author"),
                               ("year", "crossref_year"), ("doi", "crossref_doi")):
            if str(df.loc[mask, source].iloc[0]).strip():
                df.loc[mask, target] = df.loc[mask, source].iloc[0]
        df.loc[mask, "metadata_validation"] = "Manually Accepted"
    else:
        for target, source in (("title", "pdf_title"), ("author", "pdf_author"), ("year", "pdf_year")):
            if source in df.columns:
                df.loc[mask, target] = df.loc[mask, source].iloc[0]
        df.loc[mask, "metadata_validation"] = "Manually Rejected"
    df.to_csv(enriched_csv, index=False)

    reviews = _load_metadata_reviews(run_dir)
    reviews[req.filename] = {
        "filename": req.filename,
        "decision": req.decision,
        "note": req.note or "",
        "reviewed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    pd.DataFrame(list(reviews.values())).to_csv(run_dir / "metadata_reviews.csv", index=False)

    outcome = rebuild_run_outputs(run_id)
    return {"status": "success", "filename": req.filename, "decision": req.decision, "outcome": outcome}


def _paper_summary(info: dict) -> dict:
    return {
        "record_id": str(info.get("record_id", "")),
        "filename": str(info.get("filename", "")),
        "title": _clean_text(info.get("title", "")),
        "author": _clean_text(info.get("author", "")),
        "doi": str(info.get("doi", "")),
        "year": str(info.get("year", "")),
        "journal": _clean_text(info.get("crossref_journal", info.get("journal", ""))),
        "publisher": _clean_text(info.get("crossref_publisher", "")),
    }


@app.get("/api/runs/{run_id}/verification/queue")
def get_run_verification_queue(run_id: str):
    """Return duplicate candidates requiring review with side-by-side paper comparisons."""
    run_dir = get_run_dir(run_id)
    queue_csv = run_dir / "verification_queue.csv"
    results_csv = run_dir / "deduplication_results.csv"

    if not queue_csv.exists():
        info = read_run_info(run_dir)
        return {
            "candidates": [], "total": 0, "pending_count": 0,
            "queue_ready": False,
            "pipeline_status": info.get("status", "unknown"),
            "pipeline_error": info.get("error", ""),
        }

    queue_df = pd.read_csv(queue_csv).fillna("")
    results_df = pd.read_csv(results_csv).fillna("") if results_csv.exists() else pd.DataFrame()

    paper_lookup = {}
    if not results_df.empty and "record_id" in results_df.columns:
        results_df["record_id"] = results_df["record_id"].astype(str)
        paper_lookup = results_df.set_index("record_id").to_dict("index")

    candidates = []
    for _, row in queue_df.iterrows():
        matched_id = str(row.get("matched_record", ""))
        matched_info = paper_lookup.get(matched_id)
        candidate = _paper_summary(row.to_dict())
        candidate.update({
            "duplicate_status": str(row.get("duplicate_status", "")),
            "match_reason": str(row.get("match_reason", "")),
            "title_similarity": row.get("title_similarity", 0),
            "verification_status": str(row.get("verification_status", "Pending")),
            "reviewer_decision": str(row.get("reviewer_decision", "")),
            "reviewer_note": str(row.get("reviewer_note", "")),
            "reviewed_at": str(row.get("reviewed_at", "")),
            "matched_record": (
                _paper_summary({**matched_info, "record_id": matched_id}) if matched_info else None
            ),
        })
        candidates.append(candidate)

    pending_count = sum(
        1 for c in candidates
        if c["verification_status"] not in ["Confirmed Duplicate", "Not Duplicate"]
    )
    return {
        "candidates": candidates, "total": len(candidates),
        "pending_count": pending_count, "queue_ready": True,
    }


class RunDecisionRequest(BaseModel):
    record_id: str
    decision: str  # "Confirmed Duplicate", "Not Duplicate", "Pending"
    note: Optional[str] = ""


@app.post("/api/runs/{run_id}/verification/decide")
def submit_run_verification_decision(run_id: str, req: RunDecisionRequest):
    """Save reviewer decision (and optional note) persistently for a run."""
    if req.decision not in {"Confirmed Duplicate", "Not Duplicate", "Pending"}:
        raise HTTPException(status_code=400, detail=f"Unknown decision '{req.decision}'.")

    run_dir = get_run_dir(run_id)
    queue_csv = run_dir / "verification_queue.csv"

    if not queue_csv.exists():
        raise HTTPException(status_code=404, detail="Verification queue not found.")

    df = pd.read_csv(queue_csv).fillna("")
    df["record_id"] = df["record_id"].astype(str)
    for col in ("reviewer_note", "reviewed_at"):
        if col not in df.columns:
            df[col] = ""

    mask = df["record_id"] == req.record_id
    if not mask.any():
        raise HTTPException(status_code=404, detail=f"Record ID {req.record_id} not found.")

    df.loc[mask, "verification_status"] = req.decision
    df.loc[mask, "reviewer_decision"] = "" if req.decision == "Pending" else req.decision
    df.loc[mask, "reviewer_note"] = req.note or ""
    df.loc[mask, "reviewed_at"] = (
        "" if req.decision == "Pending" else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )
    df.to_csv(queue_csv, index=False)

    return {"status": "success", "record_id": req.record_id, "decision": req.decision}


@app.post("/api/runs/{run_id}/verification/finalize")
def finalize_run_verification(run_id: str):
    """Rebuild retained dataset, update PRISMA summary and generate flowchart."""
    run_dir = get_run_dir(run_id)
    results_csv = run_dir / "deduplication_results.csv"
    queue_csv = run_dir / "verification_queue.csv"
    retained_csv = run_dir / "deduplicated_records.csv"
    prisma_summary_csv = run_dir / "prisma_summary.csv"
    file_dups_csv = run_dir / "file_duplicates.csv"
    flowchart_png = run_dir / "prisma_flowchart.png"
    flowchart_pdf = run_dir / "prisma_flowchart.pdf"

    try:
        build_retained_dataset(
            dataset=run_id,
            results_file=results_csv,
            queue_file=queue_csv,
            output_file=retained_csv,
        )

        file_dups_count = len(pd.read_csv(file_dups_csv)) if file_dups_csv.exists() else 0

        generate_prisma_report(
            dataset="run",
            results_file=results_csv,
            queue_file=queue_csv,
            retained_file=retained_csv,
            report_file=prisma_summary_csv,
            file_duplicates_count=file_dups_count,
        )

        create_prisma_flowchart(
            summary_file=prisma_summary_csv,
            retained_file=retained_csv,
            png_file=flowchart_png,
            pdf_file=flowchart_pdf,
            title_text=f"PRISMA 2020 Flow Diagram – {run_id.replace('_', ' ').title()}",
        )

        return {"status": "success", "message": f"Deduplication finalized and PRISMA flowchart generated for {run_id}."}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/runs/{run_id}/prisma")
def get_run_prisma(run_id: str):
    """Return PRISMA summary metrics and flowchart availability for a run."""
    run_dir = get_run_dir(run_id)
    summary_csv = run_dir / "prisma_summary.csv"
    retained_csv = run_dir / "deduplicated_records.csv"
    flowchart_png = run_dir / "prisma_flowchart.png"

    metrics = []
    if summary_csv.exists():
        df = pd.read_csv(summary_csv)
        for _, r in df.iterrows():
            metrics.append({"metric": str(r["metric"]), "count": int(r["count"])})

    retained_records = []
    if retained_csv.exists():
        rdf = pd.read_csv(retained_csv).fillna("")
        for _, r in rdf.iterrows():
            retained_records.append({
                "filename": str(r.get("filename", "")),
                "title": str(r.get("title", "")),
                "author": str(r.get("author", "")),
                "doi": str(r.get("doi", "")),
                "year": str(r.get("year", "")),
            })

    return {
        "run_id": run_id,
        "metrics": metrics,
        "total_retained": len(retained_records),
        "retained_records": retained_records,
        "flowchart_available": flowchart_png.exists(),
    }


@app.get("/api/runs/{run_id}/flowchart.png")
def get_run_flowchart_png(run_id: str):
    run_dir = get_run_dir(run_id)
    png_path = run_dir / "prisma_flowchart.png"
    if not png_path.exists():
        raise HTTPException(status_code=404, detail="PRISMA flowchart image not found.")
    return FileResponse(png_path, media_type="image/png")


@app.get("/api/runs/{run_id}/download/{file_type}")
def download_run_file(run_id: str, file_type: str):
    run_dir = get_run_dir(run_id)
    allowed = {
        "flowchart-png": run_dir / "prisma_flowchart.png",
        "flowchart-pdf": run_dir / "prisma_flowchart.pdf",
        "retained-csv": run_dir / "deduplicated_records.csv",
        "summary-csv": run_dir / "prisma_summary.csv",
        "extracted-csv": run_dir / "pdf_extracted_metadata.csv",
        "enriched-csv": run_dir / "pdf_enriched_metadata.csv",
    }
    path = allowed.get(file_type)
    if not path or not path.exists():
        raise HTTPException(status_code=404, detail="Requested file not found.")

    ext = path.suffix.replace(".", "")
    filename = f"{run_id}_{file_type}.{ext}"
    return FileResponse(path, filename=filename)


# ==============================================================================
# Benchmark Experiment: Crossref 500 (Preserved completely separately)
# ==============================================================================

@app.get("/api/benchmark/crossref")
def get_benchmark_crossref():
    """Return the static Crossref 500 benchmark results (read-only)."""
    summary_csv = BENCHMARK_DIR / "crossref_prisma_summary.csv"
    retained_csv = BENCHMARK_DIR / "crossref_deduplicated_records.csv"
    queue_csv = BENCHMARK_DIR / "crossref_verification_queue.csv"
    results_csv = BENCHMARK_DIR / "crossref_deduplication_results.csv"

    metrics = []
    metric_map = {}
    if summary_csv.exists():
        df = pd.read_csv(summary_csv)
        for _, r in df.iterrows():
            metrics.append({"metric": str(r["metric"]), "count": int(r["count"])})
            metric_map[str(r["metric"])] = int(r["count"])

    retained_count = len(pd.read_csv(retained_csv)) if retained_csv.exists() else None

    lookup = {}
    if results_csv.exists():
        rdf = pd.read_csv(results_csv).fillna("")
        rdf["record_id"] = rdf["record_id"].astype(str)
        lookup = rdf.set_index("record_id").to_dict("index")

    def paper(rec_id, info):
        return {
            "record_id": rec_id,
            "title": _clean_text(info.get("title", "")),
            "author": _clean_text(info.get("author", "")),
            "doi": str(info.get("doi", "")),
            "year": str(info.get("year", "")),
            "journal": _clean_text(info.get("journal", "")),
            "type": str(info.get("type", "")),
            "url": str(info.get("url", "")),
        }

    candidates = []
    if queue_csv.exists():
        qdf = pd.read_csv(queue_csv).fillna("")
        for _, r in qdf.iterrows():
            matched_id = str(r.get("matched_record", ""))
            cand = paper(str(r.get("record_id", "")), r.to_dict())
            cand.update({
                "duplicate_status": str(r.get("duplicate_status", "")),
                "match_reason": str(r.get("match_reason", "")),
                "title_similarity": float(r.get("title_similarity") or 0),
                "verification_status": str(r.get("verification_status", "")),
                "reviewer_decision": str(r.get("reviewer_decision", "")),
                "reviewer_note": str(r.get("reviewer_note", "")),
                "matched_record": paper(matched_id, lookup[matched_id]) if matched_id in lookup else None,
            })
            candidates.append(cand)

    confirmed = sum(1 for c in candidates if c["verification_status"] == "Confirmed Duplicate")
    rejected = sum(1 for c in candidates if c["verification_status"] == "Not Duplicate")
    pending = len(candidates) - confirmed - rejected

    return {
        "dataset": "Crossref 500 Benchmark",
        "initial_records": metric_map.get("Records identified in input", len(lookup) or 500),
        "duplicate_candidates": len(candidates),
        "confirmed_duplicates": confirmed,
        "not_duplicates": rejected,
        "pending_verification": pending,
        "records_removed": confirmed,
        "final_retained": retained_count,
        "metrics": metrics,
        "candidates": candidates,
        "flowchart_available": (BENCHMARK_DIR / "crossref_prisma_flowchart.png").exists(),
    }


@app.get("/api/benchmark/crossref/flowchart.png")
def get_benchmark_flowchart_png():
    png_path = BENCHMARK_DIR / "crossref_prisma_flowchart.png"
    if not png_path.exists():
        raise HTTPException(status_code=404, detail="Benchmark flowchart image not found.")
    return FileResponse(png_path, media_type="image/png")


@app.get("/api/benchmark/crossref/download/{file_type}")
def download_benchmark_file(file_type: str):
    allowed = {
        "flowchart-pdf": BENCHMARK_DIR / "crossref_prisma_flowchart.pdf",
        "flowchart-png": BENCHMARK_DIR / "crossref_prisma_flowchart.png",
        "retained-csv": BENCHMARK_DIR / "crossref_deduplicated_records.csv",
        "summary-csv": BENCHMARK_DIR / "crossref_prisma_summary.csv",
    }
    path = allowed.get(file_type)
    if not path or not path.exists():
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(path, filename=f"crossref_500_{file_type}.{path.suffix.replace('.', '')}")


# ==============================================================================
# SPA Static File Serving (Production React build fallback)
# ==============================================================================

if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def serve_frontend_spa(full_path: str):
        if full_path.startswith("api"):
            raise HTTPException(status_code=404, detail="API route not found")
        file_path = FRONTEND_DIST / full_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(FRONTEND_DIST / "index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=True)
