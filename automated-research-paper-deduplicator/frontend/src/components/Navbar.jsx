import React, { useState, useEffect, useRef } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import axios from 'axios';
import { 
  Layers, 
  UploadCloud, 
  BarChart3, 
  FileSpreadsheet, 
  UserCheck, 
  FileText, 
  Database,
  History,
  ChevronDown,
  CheckCircle2,
  Trash2,
  AlertTriangle,
  X
} from 'lucide-react';

export default function Navbar({ activeRunId, setActiveRunId }) {
  const navigate = useNavigate();
  const dropdownRef = useRef(null);

  const [runs, setRuns] = useState([]);
  const [showRunsDropdown, setShowRunsDropdown] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState(null); // run_id to confirm deletion
  const [deleting, setDeleting] = useState(null); // run_id currently being deleted

  const fetchRuns = async () => {
    try {
      const res = await axios.get('/api/runs');
      setRuns(res.data.runs || []);
      // If no active run selected and runs exist, default to the latest run
      if (!activeRunId && res.data.runs && res.data.runs.length > 0) {
        setActiveRunId(res.data.runs[0].run_id);
      }
    } catch (err) {
      console.error('Error fetching runs:', err);
    }
  };

  useEffect(() => {
    fetchRuns();
    const interval = setInterval(fetchRuns, 5000);
    return () => clearInterval(interval);
  }, []);

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
        setShowRunsDropdown(false);
        setDeleteConfirm(null);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const currentRun = runs.find((r) => r.run_id === activeRunId);

  const handleDeleteRun = async (runId) => {
    try {
      setDeleting(runId);
      await axios.delete(`/api/runs/${runId}`);
      // Update local runs list
      const updatedRuns = runs.filter((r) => r.run_id !== runId);
      setRuns(updatedRuns);
      // If the deleted run was active, switch to the next available or clear
      if (activeRunId === runId) {
        const nextRun = updatedRuns[0]?.run_id || null;
        setActiveRunId(nextRun);
        if (!nextRun) {
          navigate('/');
        }
      }
      setDeleteConfirm(null);
    } catch (err) {
      console.error('Failed to delete run:', err);
      alert('Failed to delete run: ' + (err.response?.data?.detail || err.message));
    } finally {
      setDeleting(null);
      // Refresh runs list
      fetchRuns();
    }
  };

  return (
    <>
      <header className="bg-white border-b border-slate-200 sticky top-0 z-30 shadow-xs">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          {/* Brand */}
          <div 
            onClick={() => navigate('/')} 
            className="flex items-center gap-3 cursor-pointer select-none"
          >
            <div className="w-9 h-9 rounded-lg bg-blue-600 flex items-center justify-center text-white shadow-sm shadow-blue-500/20">
              <Layers className="w-5 h-5" />
            </div>
            <div>
              <h1 className="text-sm font-bold tracking-tight text-slate-900 leading-tight">
                RESEARCH DEDUPLICATOR
              </h1>
              <p className="text-[10px] text-blue-600 font-medium">PRISMA Systematic Review System</p>
            </div>
          </div>

          {/* 5 Main Navigation Links */}
          <nav className="hidden md:flex items-center gap-1">
            <NavLink
              to="/"
              end
              className={({ isActive }) =>
                `flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-semibold transition-colors ${
                  isActive
                    ? 'bg-blue-50 text-blue-700'
                    : 'text-slate-600 hover:text-slate-900 hover:bg-slate-50'
                }`
              }
            >
              <UploadCloud className="w-4 h-4" />
              <span>1. Upload PDFs</span>
            </NavLink>

            <NavLink
              to="/results"
              className={({ isActive }) =>
                `flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-semibold transition-colors ${
                  isActive
                    ? 'bg-blue-50 text-blue-700'
                    : 'text-slate-600 hover:text-slate-900 hover:bg-slate-50'
                }`
              }
            >
              <BarChart3 className="w-4 h-4" />
              <span>2. Processing Results</span>
            </NavLink>

            <NavLink
              to="/metadata"
              className={({ isActive }) =>
                `flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-semibold transition-colors ${
                  isActive
                    ? 'bg-blue-50 text-blue-700'
                    : 'text-slate-600 hover:text-slate-900 hover:bg-slate-50'
                }`
              }
            >
              <FileSpreadsheet className="w-4 h-4" />
              <span>3. Metadata</span>
            </NavLink>

            <NavLink
              to="/verification"
              className={({ isActive }) =>
                `flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-semibold transition-colors ${
                  isActive
                    ? 'bg-blue-50 text-blue-700'
                    : 'text-slate-600 hover:text-slate-900 hover:bg-slate-50'
                }`
              }
            >
              <UserCheck className="w-4 h-4" />
              <span>4. Duplicate Verification</span>
            </NavLink>

            <NavLink
              to="/prisma"
              className={({ isActive }) =>
                `flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-semibold transition-colors ${
                  isActive
                    ? 'bg-blue-50 text-blue-700'
                    : 'text-slate-600 hover:text-slate-900 hover:bg-slate-50'
                }`
              }
            >
              <FileText className="w-4 h-4" />
              <span>5. PRISMA Report</span>
            </NavLink>
          </nav>

          {/* Right Actions: Run Selector & Benchmark */}
          <div className="flex items-center gap-3">
            {/* Run History Selector */}
            <div className="relative" ref={dropdownRef}>
              <button
                onClick={() => { setShowRunsDropdown(!showRunsDropdown); setDeleteConfirm(null); }}
                className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-slate-200 bg-slate-50 hover:bg-slate-100 text-xs font-semibold text-slate-700 transition-colors"
              >
                <History className="w-3.5 h-3.5 text-blue-600" />
                <span>{currentRun ? currentRun.name || currentRun.run_id : 'No Run Active'}</span>
                <ChevronDown className="w-3.5 h-3.5 text-slate-400" />
              </button>

              {showRunsDropdown && (
                <div className="absolute right-0 mt-2 w-80 bg-white rounded-xl shadow-lg border border-slate-200 py-2 z-50">
                  <div className="px-3 py-1.5 text-[11px] font-bold text-slate-400 uppercase tracking-wider border-b border-slate-100 mb-1">
                    Processing Runs History
                  </div>
                  {runs.length === 0 ? (
                    <div className="px-4 py-3 text-xs text-slate-500 italic text-center">
                      No runs yet. Upload PDFs to start Run 001.
                    </div>
                  ) : (
                    <div className="max-h-64 overflow-y-auto">
                      {runs.map((r) => (
                        <div key={r.run_id} className="group relative">
                          {/* Delete confirmation inline for this run */}
                          {deleteConfirm === r.run_id ? (
                            <div className="mx-2 my-1 p-3 bg-rose-50 border border-rose-200 rounded-lg">
                              <div className="flex items-start gap-2 mb-2">
                                <AlertTriangle className="w-4 h-4 text-rose-600 shrink-0 mt-0.5" />
                                <div>
                                  <p className="text-xs font-bold text-rose-800">Delete this run?</p>
                                  <p className="text-[11px] text-rose-600 mt-0.5">
                                    {r.name || r.run_id} — This will permanently remove all uploaded PDFs, metadata, and results.
                                  </p>
                                </div>
                              </div>
                              <div className="flex items-center gap-2 justify-end">
                                <button
                                  onClick={() => setDeleteConfirm(null)}
                                  className="px-2.5 py-1 text-xs font-semibold text-slate-600 border border-slate-300 rounded-md hover:bg-slate-100"
                                >
                                  Cancel
                                </button>
                                <button
                                  onClick={() => handleDeleteRun(r.run_id)}
                                  disabled={deleting === r.run_id}
                                  className="px-2.5 py-1 text-xs font-bold text-white bg-rose-600 hover:bg-rose-700 rounded-md flex items-center gap-1 disabled:opacity-60"
                                >
                                  <Trash2 className="w-3 h-3" />
                                  {deleting === r.run_id ? 'Deleting...' : 'Delete'}
                                </button>
                              </div>
                            </div>
                          ) : (
                            <div
                              className={`w-full text-left px-3 py-2 text-xs flex items-center justify-between hover:bg-blue-50 transition-colors ${
                                activeRunId === r.run_id ? 'bg-blue-50/70 text-blue-700 font-bold' : 'text-slate-700'
                              }`}
                            >
                              {/* Clickable area: select run */}
                              <button
                                className="flex-1 text-left"
                                onClick={() => {
                                  setActiveRunId(r.run_id);
                                  setShowRunsDropdown(false);
                                  navigate('/results');
                                }}
                              >
                                <p className="truncate">{r.name || r.run_id}</p>
                                <p className="text-[10px] text-slate-400 font-normal">{r.created_at || 'Recent'}</p>
                              </button>

                              {/* Right side: active check + delete button */}
                              <div className="flex items-center gap-1.5 ml-2 shrink-0">
                                {activeRunId === r.run_id && (
                                  <CheckCircle2 className="w-4 h-4 text-blue-600" />
                                )}
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setDeleteConfirm(r.run_id);
                                  }}
                                  className="p-1 rounded text-slate-300 hover:text-rose-600 hover:bg-rose-50 transition-colors opacity-0 group-hover:opacity-100"
                                  title="Delete this run"
                                >
                                  <Trash2 className="w-3.5 h-3.5" />
                                </button>
                              </div>
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                  <div className="border-t border-slate-100 mt-1 pt-1 px-3">
                    <button
                      onClick={() => {
                        setShowRunsDropdown(false);
                        navigate('/');
                      }}
                      className="w-full text-center py-1.5 text-xs text-blue-600 font-bold hover:underline"
                    >
                      + Start New Run
                    </button>
                  </div>
                </div>
              )}
            </div>

            {/* Separate Crossref 500 Benchmark Link */}
            <NavLink
              to="/benchmark"
              className={({ isActive }) =>
                `flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs font-semibold transition-colors ${
                  isActive
                    ? 'bg-indigo-600 text-white border-indigo-600 shadow-xs'
                    : 'border-slate-200 bg-white text-slate-600 hover:text-indigo-600 hover:border-indigo-300'
                }`
              }
            >
              <Database className="w-3.5 h-3.5 text-indigo-500" />
              <span className="hidden sm:inline">Benchmark:</span>
              <span>Crossref 500</span>
            </NavLink>
          </div>
        </div>
      </header>
    </>
  );
}
