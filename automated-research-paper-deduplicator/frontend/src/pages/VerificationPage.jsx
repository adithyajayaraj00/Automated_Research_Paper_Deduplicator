import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { useNavigate } from 'react-router-dom';
import { 
  UserCheck, 
  CheckCircle, 
  XCircle, 
  Clock, 
  AlertTriangle, 
  RefreshCw, 
  FileCheck2, 
  ExternalLink,
  ShieldCheck,
  ArrowRight
} from 'lucide-react';

export default function VerificationPage({ activeRunId }) {
  const navigate = useNavigate();
  const [data, setData] = useState({ candidates: [], total: 0, pending_count: 0 });
  const [loading, setLoading] = useState(true);
  const [processingId, setProcessingId] = useState(null);
  const [finalizing, setFinalizing] = useState(false);
  const [message, setMessage] = useState(null);
  const [notes, setNotes] = useState({});

  // Highlight a field when the two papers disagree on it.
  const norm = (v) => String(v || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
  const differs = (a, b) => norm(a) !== norm(b);
  const diffCls = (a, b) => (differs(a, b) ? 'bg-amber-100 rounded px-1 -mx-1' : '');

  const fetchQueue = async () => {
    if (!activeRunId) {
      setLoading(false);
      return;
    }
    try {
      setLoading(true);
      const res = await axios.get(`/api/runs/${activeRunId}/verification/queue`);
      setData(res.data);
    } catch (err) {
      console.error('Error fetching verification queue:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchQueue();
  }, [activeRunId]);

  const handleDecision = async (recordId, decision) => {
    try {
      setProcessingId(recordId);
      const existing = data.candidates.find((c) => c.record_id === recordId)?.reviewer_note || '';
      const note = notes[recordId] ?? existing;
      await axios.post(`/api/runs/${activeRunId}/verification/decide`, {
        record_id: recordId,
        decision: decision,
        note,
      });

      // Update local state immediately
      setData((prev) => {
        const updated = prev.candidates.map((c) => {
          if (c.record_id === recordId) {
            return {
              ...c,
              verification_status: decision,
              reviewer_decision: decision,
              reviewer_note: notes[recordId] ?? c.reviewer_note ?? '',
            };
          }
          return c;
        });
        const pending = updated.filter(
          (c) => !['Confirmed Duplicate', 'Not Duplicate'].includes(c.verification_status)
        ).length;
        return { ...prev, candidates: updated, pending_count: pending };
      });

      setMessage({ type: 'success', text: `Saved decision: "${decision}"` });
      setTimeout(() => setMessage(null), 3000);
    } catch (err) {
      console.error('Failed to save decision:', err);
      alert('Failed to save decision: ' + (err.response?.data?.detail || err.message));
    } finally {
      setProcessingId(null);
    }
  };

  const handleFinalize = async () => {
    if (data.pending_count > 0) {
      alert(`There are still ${data.pending_count} pending candidates. Please review all candidates before finalizing.`);
      return;
    }

    try {
      setFinalizing(true);
      const res = await axios.post(`/api/runs/${activeRunId}/verification/finalize`);
      setMessage({ type: 'success', text: res.data.message });
      fetchQueue();
      setTimeout(() => navigate('/prisma'), 1200);
    } catch (err) {
      console.error('Failed to finalize:', err);
      alert('Finalization error: ' + (err.response?.data?.detail || err.message));
    } finally {
      setFinalizing(false);
    }
  };

  if (!activeRunId) {
    return (
      <div className="flex-1 p-10 flex items-center justify-center">
        <p className="text-xs text-slate-500">Please select or upload a run first.</p>
      </div>
    );
  }

  return (
    <div className="flex-1 py-10 px-6 max-w-5xl mx-auto w-full space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <span className="text-[11px] font-bold text-blue-600 uppercase tracking-wider block">
            {activeRunId} Verification
          </span>
          <h2 className="text-xl font-bold text-slate-900 leading-tight">Duplicate Verification Queue</h2>
          <p className="text-xs text-slate-500 mt-1">
            Review algorithmic duplicate candidates. No paper is automatically removed without human confirmation.
          </p>
        </div>

        <button
          onClick={handleFinalize}
          disabled={finalizing || data.pending_count > 0 || data.candidates.length === 0}
          className={`px-4 py-2 rounded-lg text-xs font-bold shadow-xs flex items-center gap-2 transition-all ${
            data.pending_count > 0 || data.candidates.length === 0
              ? 'bg-slate-200 text-slate-400 cursor-not-allowed'
              : 'bg-emerald-600 hover:bg-emerald-700 text-white'
          }`}
        >
          {finalizing ? (
            <>
              <RefreshCw className="w-4 h-4 animate-spin" />
              <span>Finalizing...</span>
            </>
          ) : (
            <>
              <FileCheck2 className="w-4 h-4" />
              <span>Finalize & Update PRISMA</span>
            </>
          )}
        </button>
      </div>

      {message && (
        <div className={`p-3 rounded-lg text-xs font-semibold ${
          message.type === 'success' ? 'bg-emerald-50 text-emerald-800 border border-emerald-200' : 'bg-rose-50 text-rose-800'
        }`}>
          {message.text}
        </div>
      )}

      {/* Queue Stats Bar */}
      <div className="grid grid-cols-3 gap-4">
        <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-xs">
          <span className="text-xs font-semibold text-slate-500 block">Total Flagged Candidates</span>
          <span className="text-xl font-bold text-slate-900 mt-1 block">{data.total}</span>
        </div>
        <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-xs">
          <span className="text-xs font-semibold text-slate-500 block">Pending Review</span>
          <span className={`text-xl font-bold mt-1 block ${data.pending_count > 0 ? 'text-amber-600' : 'text-emerald-600'}`}>
            {data.pending_count}
          </span>
        </div>
        <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-xs">
          <span className="text-xs font-semibold text-slate-500 block">Confirmed Duplicates</span>
          <span className="text-xl font-bold text-red-600 mt-1 block">
            {data.candidates.filter((c) => c.verification_status === 'Confirmed Duplicate').length}
          </span>
        </div>
      </div>

      {/* Candidate Cards */}
      {loading ? (
        <div className="bg-white border border-slate-200 rounded-xl p-12 text-center text-slate-400">
          <RefreshCw className="w-6 h-6 animate-spin text-blue-600 mx-auto mb-2" />
          <span>Loading verification queue...</span>
        </div>
      ) : data.queue_ready === false ? (
        <div className="bg-white border border-rose-200 rounded-xl p-10 text-center max-w-xl mx-auto shadow-xs">
          <AlertTriangle className="w-10 h-10 text-rose-500 mx-auto mb-3" />
          <h3 className="text-base font-bold text-slate-800">Verification queue was not created</h3>
          <p className="text-xs text-slate-500 mt-1">
            This run stopped before paper-level detection finished, so an empty queue here does not mean there are no duplicates.
          </p>
          {data.pipeline_error && (
            <p className="mt-3 text-[11px] font-mono text-rose-700 break-words">{data.pipeline_error}</p>
          )}
        </div>
      ) : data.candidates.length === 0 ? (
        <div className="bg-white border border-slate-200 rounded-xl p-12 text-center max-w-xl mx-auto shadow-xs">
          <ShieldCheck className="w-12 h-12 text-emerald-500 mx-auto mb-3" />
          <h3 className="text-base font-bold text-slate-800">No Duplicate Candidates Queued</h3>
          <p className="text-xs text-slate-500 mt-1">
            Detection finished and every unique record was classified as a distinct paper. The PRISMA report is already complete.
          </p>
          <button
            onClick={() => navigate('/prisma')}
            className="mt-4 px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-xs font-bold inline-flex items-center gap-1.5"
          >
            <span>View PRISMA Report</span>
            <ArrowRight className="w-3.5 h-3.5" />
          </button>
        </div>
      ) : (
        <div className="space-y-6">
          {data.candidates.map((cand, idx) => {
            const isConfirmed = cand.verification_status === 'Confirmed Duplicate';
            const isRejected = cand.verification_status === 'Not Duplicate';
            const isPending = !isConfirmed && !isRejected;

            return (
              <div
                key={cand.record_id || idx}
                className={`bg-white border rounded-xl overflow-hidden shadow-xs transition-shadow hover:shadow-md ${
                  isConfirmed 
                    ? 'border-red-200 bg-red-50/15' 
                    : isRejected 
                    ? 'border-blue-200 bg-blue-50/15' 
                    : 'border-slate-200'
                }`}
              >
                {/* Header */}
                <div className="px-6 py-3 border-b border-slate-100 bg-slate-50 flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <span className="text-xs font-bold text-slate-900">Candidate #{idx + 1}</span>
                    <span className={`text-xs font-semibold px-2.5 py-0.5 rounded-full ${
                      cand.match_reason === 'Exact File Duplicate (SHA-256)'
                        ? 'bg-orange-100 text-orange-800 border border-orange-300'
                        : 'bg-slate-200 text-slate-800'
                    }`}>
                      {cand.match_reason === 'Exact File Duplicate (SHA-256)' ? '🔒 Exact File Duplicate (SHA-256)' : `Reason: ${cand.match_reason}`}
                    </span>
                    {cand.title_similarity > 0 && cand.match_reason !== 'Exact File Duplicate (SHA-256)' && (
                      <span className="text-xs font-semibold text-blue-700 bg-blue-50 px-2 py-0.5 rounded border border-blue-200">
                        Similarity: {parseFloat(cand.title_similarity).toFixed(1)}%
                      </span>
                    )}
                    {cand.match_reason === 'Exact File Duplicate (SHA-256)' && (
                      <span className="text-xs font-semibold text-orange-700 bg-orange-50 px-2 py-0.5 rounded border border-orange-200">
                        100% identical file
                      </span>
                    )}
                  </div>

                  <div className="flex items-center gap-2">
                    {isConfirmed && (
                      <span className="inline-flex items-center gap-1 text-xs font-bold text-red-700 bg-red-100 px-2.5 py-0.5 rounded-full">
                        <XCircle className="w-3.5 h-3.5" />
                        <span>Confirmed Duplicate (Will be removed)</span>
                      </span>
                    )}
                    {isRejected && (
                      <span className="inline-flex items-center gap-1 text-xs font-bold text-blue-700 bg-blue-100 px-2.5 py-0.5 rounded-full">
                        <CheckCircle className="w-3.5 h-3.5" />
                        <span>Not Duplicate (Retained)</span>
                      </span>
                    )}
                    {isPending && (
                      <span className="inline-flex items-center gap-1 text-xs font-bold text-amber-700 bg-amber-100 px-2.5 py-0.5 rounded-full">
                        <Clock className="w-3.5 h-3.5" />
                        <span>Pending Decision</span>
                      </span>
                    )}
                  </div>
                </div>

                {/* Side-by-Side Comparison: Candidate Paper A vs Reference Paper B */}
                <div className="p-6 grid grid-cols-1 md:grid-cols-2 gap-6">
                  {/* Left: Paper A (Candidate) */}
                  <div className="space-y-2 border border-slate-200 rounded-lg p-4 bg-slate-50/50">
                    <span className="text-[11px] font-bold uppercase tracking-wider text-rose-600 block">
                      Paper A (Flagged Candidate)
                    </span>
                    <h4 className="text-xs font-bold text-slate-900 leading-snug">{cand.title}</h4>
                    <div className="text-xs space-y-1 text-slate-600 pt-2">
                      <p><strong className="text-slate-800">Authors:</strong> <span className={cand.matched_record ? diffCls(cand.author, cand.matched_record.author) : ''}>{cand.author || '—'}</span></p>
                      <p><strong className="text-slate-800">DOI:</strong> <span className={`font-mono text-blue-700 ${cand.matched_record ? diffCls(cand.doi, cand.matched_record.doi) : ''}`}>{cand.doi || '—'}</span></p>
                      <p><strong className="text-slate-800">Year:</strong> <span className={cand.matched_record ? diffCls(cand.year, cand.matched_record.year) : ''}>{cand.year || '—'}</span></p>
                      {cand.journal && <p><strong className="text-slate-800">Journal:</strong> <span className={cand.matched_record ? diffCls(cand.journal, cand.matched_record.journal) : ''}>{cand.journal}</span></p>}
                      {cand.filename && <p><strong className="text-slate-800">File:</strong> {cand.filename}</p>}
                    </div>
                  </div>

                  {/* Right: Paper B (Matched Record) */}
                  <div className="space-y-2 border border-blue-200 rounded-lg p-4 bg-blue-50/30">
                    <span className="text-[11px] font-bold uppercase tracking-wider text-blue-700 block">
                      {cand.match_reason === 'Exact File Duplicate (SHA-256)'
                        ? 'Original File (SHA-256 Match)'
                        : 'Paper B (Matched Reference Paper)'}
                    </span>
                    {cand.matched_record ? (
                      <>
                        <h4 className="text-xs font-bold text-slate-900 leading-snug">{cand.matched_record.title}</h4>
                        <div className="text-xs space-y-1 text-slate-600 pt-2">
                          <p><strong className="text-slate-800">Authors:</strong> <span className={diffCls(cand.author, cand.matched_record.author)}>{cand.matched_record.author || '—'}</span></p>
                          <p><strong className="text-slate-800">DOI:</strong> <span className={`font-mono text-blue-700 ${diffCls(cand.doi, cand.matched_record.doi)}`}>{cand.matched_record.doi || '—'}</span></p>
                          <p><strong className="text-slate-800">Year:</strong> <span className={diffCls(cand.year, cand.matched_record.year)}>{cand.matched_record.year || '—'}</span></p>
                          {cand.matched_record.journal && <p><strong className="text-slate-800">Journal:</strong> <span className={diffCls(cand.journal, cand.matched_record.journal)}>{cand.matched_record.journal}</span></p>}
                          {cand.matched_record.filename && <p><strong className="text-slate-800">File:</strong> {cand.matched_record.filename}</p>}
                        </div>
                      </>
                    ) : cand.match_reason === 'Exact File Duplicate (SHA-256)' ? (
                      <div className="text-xs text-slate-600 space-y-1 pt-1">
                        <p className="text-orange-700 font-semibold text-[11px] pb-1">This file is a byte-for-byte duplicate of another uploaded PDF (same SHA-256 hash). The original file was processed separately.</p>
                        <p><strong className="text-slate-800">Title:</strong> {cand.title || '—'}</p>
                        <p><strong className="text-slate-800">Authors:</strong> {cand.author || '—'}</p>
                        <p><strong className="text-slate-800">DOI:</strong> <span className="font-mono text-blue-700">{cand.doi || '—'}</span></p>
                        <p><strong className="text-slate-800">SHA-256:</strong> <span className="font-mono text-[10px] text-slate-500">{cand.file_hash || '—'}</span></p>
                      </div>
                    ) : (
                      <p className="text-xs text-slate-400 italic">Matched paper record details unavailable.</p>
                    )}
                  </div>
                </div>

                <div className="px-6 pb-4 space-y-2">
                  <p className="text-[11px] text-slate-400">Highlighted fields differ between the two papers.</p>
                  <input
                    type="text"
                    value={notes[cand.record_id] ?? cand.reviewer_note ?? ''}
                    onChange={(e) => setNotes((prev) => ({ ...prev, [cand.record_id]: e.target.value }))}
                    placeholder="Optional reviewer note (saved with your decision)"
                    className="w-full px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-xs text-slate-800 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:bg-white"
                  />
                </div>

                {/* Card Decision Action Buttons */}
                <div className="px-6 py-3 bg-slate-50 border-t border-slate-100 flex items-center justify-between">
                  <span className="text-xs text-slate-500 font-medium">Record ID: {cand.record_id}</span>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => handleDecision(cand.record_id, 'Confirmed Duplicate')}
                      disabled={processingId === cand.record_id}
                      className="px-3.5 py-1.5 rounded-lg bg-red-600 hover:bg-red-700 text-white text-xs font-semibold transition-colors flex items-center gap-1.5 shadow-2xs"
                    >
                      <XCircle className="w-3.5 h-3.5" />
                      <span>Confirm Duplicate</span>
                    </button>

                    <button
                      onClick={() => handleDecision(cand.record_id, 'Not Duplicate')}
                      disabled={processingId === cand.record_id}
                      className="px-3.5 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold transition-colors flex items-center gap-1.5 shadow-2xs"
                    >
                      <CheckCircle className="w-3.5 h-3.5" />
                      <span>Not a Duplicate</span>
                    </button>

                    <button
                      onClick={() => handleDecision(cand.record_id, 'Pending')}
                      disabled={processingId === cand.record_id}
                      className="px-3 py-1.5 rounded-lg border border-slate-300 hover:bg-slate-100 text-slate-700 text-xs font-semibold transition-colors"
                    >
                      Keep Pending
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
