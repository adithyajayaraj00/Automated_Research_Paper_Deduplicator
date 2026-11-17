import React, { useState, useEffect } from 'react';
import axios from 'axios';
import {
  Database,
  Download,
  RefreshCw,
  X,
  ExternalLink,
  CheckCircle2,
  XCircle,
  ChevronRight,
} from 'lucide-react';

// ---- helpers ---------------------------------------------------------------
const norm = (v) => String(v || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
const same = (a, b) => norm(a) !== '' && norm(a) === norm(b);
const differs = (a, b) => norm(a) !== norm(b);

const statusStyle = (status) =>
  status === 'Not Duplicate'
    ? 'bg-blue-100 text-blue-800'
    : status === 'Confirmed Duplicate'
    ? 'bg-red-100 text-red-800'
    : 'bg-amber-100 text-amber-800';

function EvidenceChip({ label, ok, detail }) {
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-semibold border ${
        ok ? 'bg-emerald-50 text-emerald-800 border-emerald-200' : 'bg-rose-50 text-rose-800 border-rose-200'
      }`}
    >
      {ok ? <CheckCircle2 className="w-3 h-3" /> : <XCircle className="w-3 h-3" />}
      {label}
      {detail ? `: ${detail}` : ''}
    </span>
  );
}

function Row({ label, a, b, mono = false }) {
  const diff = differs(a, b);
  const cell = (v) => (
    <p className={`mt-0.5 break-words ${mono ? 'font-mono text-blue-700' : 'font-semibold text-slate-800'} ${diff ? 'bg-amber-100 rounded px-1 -mx-1' : ''}`}>
      {v || <span className="text-slate-400 italic font-normal">—</span>}
    </p>
  );
  return (
    <div className="grid grid-cols-[84px_1fr_1fr] gap-3 py-2 border-b border-slate-100 last:border-0 text-xs">
      <span className="text-slate-400 font-medium">{label}</span>
      <div>{cell(a)}</div>
      <div>{cell(b)}</div>
    </div>
  );
}

// ---- page ------------------------------------------------------------------
export default function BenchmarkPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selectedIdx, setSelectedIdx] = useState(null);

  const fetchBenchmark = async () => {
    try {
      setLoading(true);
      const res = await axios.get('/api/benchmark/crossref');
      setData(res.data);
    } catch (err) {
      console.error('Error fetching benchmark:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchBenchmark();
  }, []);

  // close the drawer with Escape
  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && setSelectedIdx(null);
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  if (loading) {
    return (
      <div className="flex-1 p-10 flex items-center justify-center">
        <RefreshCw className="w-6 h-6 animate-spin text-blue-600 mx-auto" />
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex-1 p-10 text-center text-xs text-slate-500">
        Benchmark results could not be loaded. Is the API server running?
      </div>
    );
  }

  const candidates = data.candidates || [];
  const selected = selectedIdx !== null ? candidates[selectedIdx] : null;
  const m = selected?.matched_record;

  const statCards = [
    { label: 'Initial Crossref Records', value: data.initial_records, color: 'text-indigo-600' },
    { label: 'Duplicate Candidates', value: data.duplicate_candidates, color: 'text-amber-600' },
    { label: 'Confirmed Duplicates', value: data.confirmed_duplicates, color: 'text-red-600' },
    { label: 'Not Duplicate (Retained)', value: data.not_duplicates, color: 'text-blue-600' },
    { label: 'Pending Verification', value: data.pending_verification, color: 'text-slate-600' },
    { label: 'Final Retained Records', value: data.final_retained ?? '—', color: 'text-emerald-600', highlight: true },
  ];

  return (
    <div className="flex-1 py-10 px-6 max-w-5xl mx-auto w-full space-y-8">
      {/* Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <div className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-indigo-50 border border-indigo-200 text-indigo-700 text-xs font-bold mb-1">
            <Database className="w-3.5 h-3.5" />
            <span>Isolated Baseline Benchmark</span>
          </div>
          <h2 className="text-xl font-bold text-slate-900 leading-tight">Benchmark Experiment – Crossref 500</h2>
          <p className="text-xs text-slate-500 mt-1">
            Metadata-level deduplication with human-in-the-loop review. Select any decision to see the evidence.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <a
            href="/api/benchmark/crossref/download/retained-csv"
            download
            className="px-3 py-1.5 bg-white border border-slate-300 hover:bg-slate-50 text-slate-700 text-xs font-semibold rounded-lg flex items-center gap-1.5 shadow-2xs"
          >
            <Download className="w-3.5 h-3.5" />
            <span>Retained CSV ({data.final_retained ?? '—'})</span>
          </a>
          <a
            href="/api/benchmark/crossref/download/flowchart-pdf"
            download
            className="px-3.5 py-1.5 bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-semibold rounded-lg flex items-center gap-1.5 shadow-2xs"
          >
            <Download className="w-3.5 h-3.5" />
            <span>Flowchart PDF</span>
          </a>
        </div>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        {statCards.map((c, i) => (
          <div
            key={i}
            className={`bg-white border rounded-xl p-4 shadow-xs ${
              c.highlight ? 'border-emerald-300 bg-emerald-50/20' : 'border-slate-200'
            }`}
          >
            <span className="text-[11px] font-semibold text-slate-500 block leading-tight">{c.label}</span>
            <span className={`text-xl font-bold mt-1 block ${c.color}`}>{c.value}</span>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
        {/* Left: flowchart */}
        <div className="lg:col-span-7 bg-white border border-slate-200 rounded-xl p-6 shadow-xs space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-bold text-slate-900">Benchmark PRISMA Flowchart</h3>
            <span className="text-[11px] font-bold text-emerald-700 bg-emerald-50 px-2.5 py-0.5 rounded border border-emerald-200">
              {data.initial_records} → {data.final_retained ?? '—'} Retained
            </span>
          </div>
          <div className="border border-slate-200 rounded-lg p-2 bg-slate-50/50 flex items-center justify-center min-h-[420px]">
            <img
              src="/api/benchmark/crossref/flowchart.png"
              alt="Crossref 500 Benchmark PRISMA Flowchart"
              className="max-w-full h-auto rounded shadow-2xs"
            />
          </div>
        </div>

        {/* Right: selectable verification decisions */}
        <div className="lg:col-span-5 bg-white border border-slate-200 rounded-xl p-6 shadow-xs space-y-4">
          <div>
            <h3 className="text-sm font-bold text-slate-900">Verification Decisions</h3>
            <p className="text-xs text-slate-500">
              {candidates.length} duplicate candidates reviewed by a human reviewer. Click one to open its details.
            </p>
          </div>

          <div className="space-y-3">
            {candidates.map((cand, i) => (
              <button
                key={cand.record_id || i}
                onClick={() => setSelectedIdx(i)}
                className={`w-full text-left p-3 rounded-lg border text-xs space-y-1 transition-all hover:shadow-md hover:border-indigo-300 focus:outline-none focus:ring-2 focus:ring-indigo-400 ${
                  selectedIdx === i ? 'border-indigo-400 bg-indigo-50/50 shadow-md' : 'border-slate-200 bg-slate-50/50'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-bold text-slate-800">#{i + 1} {cand.match_reason}</span>
                  <span className={`font-bold text-[10px] px-2 py-0.5 rounded ${statusStyle(cand.verification_status)}`}>
                    {cand.verification_status}
                  </span>
                </div>
                <p className="font-semibold text-slate-900 leading-snug">{cand.title}</p>
                <div className="text-[11px] text-slate-500 flex items-center justify-between pt-1">
                  <span>Similarity: {Number(cand.title_similarity || 0).toFixed(1)}%</span>
                  <span className="inline-flex items-center gap-0.5 text-indigo-600 font-semibold">
                    View details <ChevronRight className="w-3 h-3" />
                  </span>
                </div>
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Detail drawer */}
      {selected && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-end bg-slate-900/40 backdrop-blur-xs"
          onClick={() => setSelectedIdx(null)}
        >
          <div
            className="w-full max-w-2xl bg-white h-full shadow-2xl flex flex-col overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="p-6 border-b border-slate-200 flex items-start justify-between bg-slate-50 sticky top-0 z-10">
              <div>
                <span className="text-[11px] font-bold uppercase tracking-wider text-indigo-600 block mb-0.5">
                  Decision #{selectedIdx + 1} of {candidates.length}
                </span>
                <h3 className="text-sm font-bold text-slate-900 leading-snug max-w-md">{selected.title}</h3>
                <div className="flex items-center gap-2 mt-2">
                  <span className={`font-bold text-[11px] px-2 py-0.5 rounded ${statusStyle(selected.verification_status)}`}>
                    {selected.verification_status}
                  </span>
                  <span className="text-[11px] font-semibold text-slate-600 bg-slate-200 px-2 py-0.5 rounded">
                    {selected.duplicate_status}: {selected.match_reason}
                  </span>
                </div>
              </div>
              <button
                onClick={() => setSelectedIdx(null)}
                className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-200"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="p-6 space-y-6">
              {/* Evidence summary */}
              <div className="space-y-2">
                <span className="text-xs font-bold text-slate-800 block">Evidence the reviewer had</span>
                {m ? (
                  <div className="flex flex-wrap gap-2">
                    <EvidenceChip label="Title similarity" ok={Number(selected.title_similarity) >= 85} detail={`${Number(selected.title_similarity).toFixed(1)}%`} />
                    <EvidenceChip label="Same DOI" ok={same(selected.doi, m.doi)} />
                    <EvidenceChip label="Same authors" ok={same(selected.author, m.author)} />
                    <EvidenceChip label="Same year" ok={same(selected.year, m.year)} />
                    <EvidenceChip label="Same journal" ok={same(selected.journal, m.journal)} />
                  </div>
                ) : (
                  <p className="text-xs text-slate-400 italic">The matched record is not in the results file.</p>
                )}
              </div>

              {/* Side by side */}
              <div className="border border-slate-200 rounded-xl p-4">
                <div className="grid grid-cols-[84px_1fr_1fr] gap-3 pb-2 border-b border-slate-200 text-[11px] font-bold uppercase tracking-wider">
                  <span />
                  <span className="text-rose-600">Flagged record</span>
                  <span className="text-blue-700">Matched record</span>
                </div>
                <Row label="Title" a={selected.title} b={m?.title} />
                <Row label="Authors" a={selected.author} b={m?.author} />
                <Row label="DOI" a={selected.doi} b={m?.doi} mono />
                <Row label="Year" a={selected.year} b={m?.year} />
                <Row label="Journal" a={selected.journal} b={m?.journal} />
                <Row label="Type" a={selected.type} b={m?.type} />
              </div>
              <p className="text-[11px] text-slate-400 -mt-3">Highlighted rows differ between the two records.</p>

              {/* Links */}
              <div className="flex flex-wrap gap-3 text-xs">
                {selected.url && (
                  <a href={selected.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-blue-700 font-semibold hover:underline">
                    <ExternalLink className="w-3 h-3" /> Open flagged record
                  </a>
                )}
                {m?.url && (
                  <a href={m.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-blue-700 font-semibold hover:underline">
                    <ExternalLink className="w-3 h-3" /> Open matched record
                  </a>
                )}
              </div>

              {/* Outcome */}
              <div className={`p-4 rounded-xl border text-xs ${
                selected.verification_status === 'Confirmed Duplicate'
                  ? 'bg-red-50 border-red-200 text-red-900'
                  : 'bg-blue-50 border-blue-200 text-blue-900'
              }`}>
                <strong>Outcome: </strong>
                {selected.verification_status === 'Confirmed Duplicate'
                  ? 'the reviewer confirmed this as a duplicate, so the flagged record was removed from the retained dataset.'
                  : selected.verification_status === 'Not Duplicate'
                  ? 'the reviewer judged these to be different publications, so the flagged record was kept.'
                  : 'no reviewer decision is stored for this candidate.'}
                {selected.reviewer_note && <p className="mt-1 italic">Reviewer note: {selected.reviewer_note}</p>}
              </div>
            </div>

            <div className="p-4 border-t border-slate-200 bg-slate-50 mt-auto flex items-center justify-between">
              <div className="flex gap-2">
                <button
                  disabled={selectedIdx === 0}
                  onClick={() => setSelectedIdx(selectedIdx - 1)}
                  className="px-3 py-1.5 rounded-lg border border-slate-300 text-xs font-semibold text-slate-700 disabled:opacity-40 hover:bg-white"
                >
                  ← Previous
                </button>
                <button
                  disabled={selectedIdx === candidates.length - 1}
                  onClick={() => setSelectedIdx(selectedIdx + 1)}
                  className="px-3 py-1.5 rounded-lg border border-slate-300 text-xs font-semibold text-slate-700 disabled:opacity-40 hover:bg-white"
                >
                  Next →
                </button>
              </div>
              <button
                onClick={() => setSelectedIdx(null)}
                className="px-4 py-2 bg-slate-800 hover:bg-slate-900 text-white rounded-lg text-xs font-semibold"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
