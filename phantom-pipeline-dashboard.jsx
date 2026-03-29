import { useState, useEffect, useCallback } from "react";

const PHASES = ["idea", "architecture", "export", "build", "review", "fix", "deploy", "done"];
const PHASE_ICONS = { idea: "💡", architecture: "🏗️", export: "📦", build: "🔨", review: "🔍", fix: "🔧", deploy: "🚀", done: "✅" };
const AUTHOR_COLORS = { sneaks: "#f59e0b", chatgpt: "#10b981", claude: "#8b5cf6", claude_code: "#3b82f6" };

const API_BASE = ""; // Set to your Zeabur URL

export default function PhantomPipeline() {
  const [apiUrl, setApiUrl] = useState(API_BASE);
  const [projects, setProjects] = useState([]);
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [newName, setNewName] = useState("");
  const [entryAuthor, setEntryAuthor] = useState("sneaks");
  const [entryType, setEntryType] = useState("input");
  const [entryContent, setEntryContent] = useState("");
  const [exportResult, setExportResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [view, setView] = useState("projects"); // projects | detail | export

  const api = useCallback(async (path, opts = {}) => {
    if (!apiUrl) throw new Error("Set API URL first");
    const res = await fetch(`${apiUrl}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...opts,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    return res.json();
  }, [apiUrl]);

  const load = useCallback(async () => {
    if (!apiUrl) return;
    try {
      setLoading(true);
      const data = await api("/projects");
      setProjects(data);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [api, apiUrl]);

  const loadDetail = useCallback(async (id) => {
    try {
      setLoading(true);
      const data = await api(`/projects/${id}`);
      setDetail(data);
      setSelected(id);
      setView("detail");
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [api]);

  useEffect(() => { load(); }, [load]);

  const createProject = async () => {
    if (!newName.trim()) return;
    try {
      const p = await api("/projects", { method: "POST", body: JSON.stringify({ name: newName }) });
      setNewName("");
      await load();
      await loadDetail(p.id);
    } catch (e) { setError(e.message); }
  };

  const addEntry = async () => {
    if (!entryContent.trim() || !selected) return;
    try {
      await api(`/projects/${selected}/entries`, {
        method: "POST",
        body: JSON.stringify({ author: entryAuthor, content: entryContent, entry_type: entryType }),
      });
      setEntryContent("");
      await loadDetail(selected);
    } catch (e) { setError(e.message); }
  };

  const advance = async () => {
    if (!selected) return;
    try {
      await api(`/projects/${selected}/advance`, { method: "POST", body: JSON.stringify({}) });
      await loadDetail(selected);
      await load();
    } catch (e) { setError(e.message); }
  };

  const rollback = async () => {
    if (!selected) return;
    try {
      await api(`/projects/${selected}/rollback`, { method: "POST" });
      await loadDetail(selected);
      await load();
    } catch (e) { setError(e.message); }
  };

  const generateExport = async () => {
    if (!selected) return;
    try {
      const data = await api(`/projects/${selected}/export`, { method: "POST", body: JSON.stringify({}) });
      setExportResult(data.spec_bundle);
      setView("export");
    } catch (e) { setError(e.message); }
  };

  const deleteProject = async (id) => {
    try {
      await api(`/projects/${id}`, { method: "DELETE" });
      if (selected === id) { setSelected(null); setDetail(null); setView("projects"); }
      await load();
    } catch (e) { setError(e.message); }
  };

  const phaseIndex = detail ? PHASES.indexOf(detail.phase) : -1;

  return (
    <div style={{
      minHeight: "100vh",
      background: "linear-gradient(145deg, #0a0a0f 0%, #12121f 50%, #0d0d18 100%)",
      color: "#e2e8f0",
      fontFamily: "'JetBrains Mono', 'SF Mono', 'Fira Code', monospace",
      padding: "24px",
    }}>
      {/* Error toast */}
      {error && (
        <div style={{
          position: "fixed", top: 16, right: 16, background: "#dc2626", color: "#fff",
          padding: "12px 20px", borderRadius: 8, fontSize: 13, zIndex: 100,
          cursor: "pointer", maxWidth: 400,
        }} onClick={() => setError(null)}>
          ⚠ {error}
        </div>
      )}

      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 32 }}>
        <div>
          <h1 style={{
            fontSize: 28, fontWeight: 800, margin: 0,
            background: "linear-gradient(135deg, #8b5cf6, #06b6d4)",
            WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent",
          }}>
            PHANTOM PIPELINE
          </h1>
          <p style={{ margin: "4px 0 0", fontSize: 12, color: "#64748b", letterSpacing: 2 }}>
            AUTONOMOUS DEV ORCHESTRATOR
          </p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <input
            value={apiUrl}
            onChange={e => setApiUrl(e.target.value)}
            placeholder="https://your-pipeline.zeabur.app"
            style={{
              background: "#1e1e2e", border: "1px solid #2d2d44", borderRadius: 6,
              color: "#e2e8f0", padding: "8px 12px", fontSize: 12, width: 280,
              fontFamily: "inherit",
            }}
          />
          <button onClick={load} style={{
            background: "#2d2d44", border: "none", borderRadius: 6,
            color: "#e2e8f0", padding: "8px 16px", fontSize: 12, cursor: "pointer",
            fontFamily: "inherit",
          }}>
            {loading ? "..." : "Connect"}
          </button>
        </div>
      </div>

      <div style={{ display: "flex", gap: 24 }}>
        {/* Sidebar — Project List */}
        <div style={{ width: 280, flexShrink: 0 }}>
          <div style={{
            background: "#13131f", border: "1px solid #1e1e2e", borderRadius: 12,
            padding: 16, marginBottom: 16,
          }}>
            <div style={{ fontSize: 11, color: "#64748b", letterSpacing: 1.5, marginBottom: 12 }}>NEW PROJECT</div>
            <input
              value={newName}
              onChange={e => setNewName(e.target.value)}
              onKeyDown={e => e.key === "Enter" && createProject()}
              placeholder="Project name..."
              style={{
                width: "100%", background: "#1e1e2e", border: "1px solid #2d2d44",
                borderRadius: 6, color: "#e2e8f0", padding: "8px 10px", fontSize: 13,
                fontFamily: "inherit", boxSizing: "border-box", marginBottom: 8,
              }}
            />
            <button onClick={createProject} style={{
              width: "100%", background: "linear-gradient(135deg, #8b5cf6, #6d28d9)",
              border: "none", borderRadius: 6, color: "#fff", padding: "8px",
              fontSize: 12, cursor: "pointer", fontFamily: "inherit", fontWeight: 600,
            }}>
              + CREATE
            </button>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {projects.map(p => (
              <div
                key={p.id}
                onClick={() => loadDetail(p.id)}
                style={{
                  background: selected === p.id ? "#1e1e3a" : "#13131f",
                  border: `1px solid ${selected === p.id ? "#8b5cf6" : "#1e1e2e"}`,
                  borderRadius: 10, padding: "12px 14px", cursor: "pointer",
                  transition: "all 0.15s ease",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span style={{ fontSize: 13, fontWeight: 600 }}>{p.name}</span>
                  <span style={{ fontSize: 18 }}>{PHASE_ICONS[p.phase]}</span>
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", marginTop: 6 }}>
                  <span style={{ fontSize: 10, color: "#64748b" }}>{p.id}</span>
                  <span style={{
                    fontSize: 10, color: "#8b5cf6", textTransform: "uppercase",
                    letterSpacing: 1, fontWeight: 600,
                  }}>{p.phase}</span>
                </div>
              </div>
            ))}
            {projects.length === 0 && (
              <div style={{ textAlign: "center", color: "#475569", fontSize: 12, padding: 24 }}>
                {apiUrl ? "No projects yet" : "Set API URL to connect"}
              </div>
            )}
          </div>
        </div>

        {/* Main Panel */}
        <div style={{ flex: 1, minWidth: 0 }}>
          {!detail && view === "projects" && (
            <div style={{
              display: "flex", alignItems: "center", justifyContent: "center",
              height: 400, color: "#475569", fontSize: 14,
            }}>
              Select a project or create one
            </div>
          )}

          {detail && view === "detail" && (
            <div>
              {/* Phase Progress Bar */}
              <div style={{
                background: "#13131f", border: "1px solid #1e1e2e", borderRadius: 12,
                padding: 20, marginBottom: 20,
              }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
                  <h2 style={{ margin: 0, fontSize: 18 }}>{detail.name}</h2>
                  <div style={{ display: "flex", gap: 8 }}>
                    <button onClick={rollback} style={{
                      background: "#1e1e2e", border: "1px solid #2d2d44", borderRadius: 6,
                      color: "#94a3b8", padding: "6px 14px", fontSize: 11, cursor: "pointer",
                      fontFamily: "inherit",
                    }}>⏪ BACK</button>
                    <button onClick={advance} style={{
                      background: "linear-gradient(135deg, #06b6d4, #0891b2)",
                      border: "none", borderRadius: 6, color: "#fff",
                      padding: "6px 14px", fontSize: 11, cursor: "pointer",
                      fontFamily: "inherit", fontWeight: 600,
                    }}>ADVANCE ⏩</button>
                    <button onClick={generateExport} style={{
                      background: "linear-gradient(135deg, #f59e0b, #d97706)",
                      border: "none", borderRadius: 6, color: "#fff",
                      padding: "6px 14px", fontSize: 11, cursor: "pointer",
                      fontFamily: "inherit", fontWeight: 600,
                    }}>📦 EXPORT</button>
                    <button onClick={() => deleteProject(detail.id)} style={{
                      background: "#1e1e2e", border: "1px solid #dc2626", borderRadius: 6,
                      color: "#dc2626", padding: "6px 14px", fontSize: 11, cursor: "pointer",
                      fontFamily: "inherit",
                    }}>🗑️</button>
                  </div>
                </div>

                {/* Phase dots */}
                <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
                  {PHASES.map((ph, i) => (
                    <div key={ph} style={{ display: "flex", alignItems: "center", flex: 1 }}>
                      <div style={{
                        width: 32, height: 32, borderRadius: "50%",
                        display: "flex", alignItems: "center", justifyContent: "center",
                        fontSize: 14,
                        background: i < phaseIndex ? "#8b5cf6" : i === phaseIndex ? "#06b6d4" : "#1e1e2e",
                        border: i === phaseIndex ? "2px solid #06b6d4" : "2px solid transparent",
                        transition: "all 0.2s",
                      }}>
                        {PHASE_ICONS[ph]}
                      </div>
                      {i < PHASES.length - 1 && (
                        <div style={{
                          flex: 1, height: 2, marginLeft: 4, marginRight: 4,
                          background: i < phaseIndex ? "#8b5cf6" : "#1e1e2e",
                        }} />
                      )}
                    </div>
                  ))}
                </div>
                <div style={{ display: "flex", gap: 4, marginTop: 6 }}>
                  {PHASES.map((ph, i) => (
                    <div key={ph} style={{
                      flex: 1, textAlign: "center", fontSize: 9,
                      color: i === phaseIndex ? "#06b6d4" : "#475569",
                      textTransform: "uppercase", letterSpacing: 0.5,
                    }}>{ph}</div>
                  ))}
                </div>
              </div>

              {/* Add Entry */}
              <div style={{
                background: "#13131f", border: "1px solid #1e1e2e", borderRadius: 12,
                padding: 20, marginBottom: 20,
              }}>
                <div style={{ fontSize: 11, color: "#64748b", letterSpacing: 1.5, marginBottom: 12 }}>
                  ADD ENTRY — {detail.phase.toUpperCase()}
                </div>
                <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
                  {["sneaks", "chatgpt", "claude", "claude_code"].map(a => (
                    <button key={a} onClick={() => setEntryAuthor(a)} style={{
                      background: entryAuthor === a ? AUTHOR_COLORS[a] + "22" : "#1e1e2e",
                      border: `1px solid ${entryAuthor === a ? AUTHOR_COLORS[a] : "#2d2d44"}`,
                      borderRadius: 6, color: entryAuthor === a ? AUTHOR_COLORS[a] : "#64748b",
                      padding: "4px 10px", fontSize: 11, cursor: "pointer",
                      fontFamily: "inherit", fontWeight: entryAuthor === a ? 700 : 400,
                    }}>{a}</button>
                  ))}
                  <div style={{ width: 1, background: "#2d2d44" }} />
                  {["input", "validation", "review", "fix", "approval"].map(t => (
                    <button key={t} onClick={() => setEntryType(t)} style={{
                      background: entryType === t ? "#2d2d44" : "transparent",
                      border: `1px solid ${entryType === t ? "#475569" : "#2d2d44"}`,
                      borderRadius: 6, color: entryType === t ? "#e2e8f0" : "#475569",
                      padding: "4px 10px", fontSize: 11, cursor: "pointer",
                      fontFamily: "inherit",
                    }}>{t}</button>
                  ))}
                </div>
                <textarea
                  value={entryContent}
                  onChange={e => setEntryContent(e.target.value)}
                  placeholder="Paste spec, validation, review notes, code output..."
                  rows={6}
                  style={{
                    width: "100%", background: "#0a0a14", border: "1px solid #2d2d44",
                    borderRadius: 8, color: "#e2e8f0", padding: 12, fontSize: 13,
                    fontFamily: "inherit", resize: "vertical", boxSizing: "border-box",
                  }}
                />
                <button onClick={addEntry} style={{
                  marginTop: 8, background: "linear-gradient(135deg, #8b5cf6, #6d28d9)",
                  border: "none", borderRadius: 6, color: "#fff", padding: "8px 24px",
                  fontSize: 12, cursor: "pointer", fontFamily: "inherit", fontWeight: 600,
                }}>
                  SUBMIT ENTRY
                </button>
              </div>

              {/* Timeline */}
              <div style={{
                background: "#13131f", border: "1px solid #1e1e2e", borderRadius: 12,
                padding: 20,
              }}>
                <div style={{ fontSize: 11, color: "#64748b", letterSpacing: 1.5, marginBottom: 16 }}>
                  TIMELINE ({detail.entries?.length || 0} entries)
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  {(detail.entries || []).map(e => (
                    <div key={e.id} style={{
                      background: "#0a0a14", borderRadius: 8, padding: 14,
                      borderLeft: `3px solid ${AUTHOR_COLORS[e.author] || "#475569"}`,
                    }}>
                      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                          <span style={{
                            color: AUTHOR_COLORS[e.author] || "#94a3b8",
                            fontWeight: 700, fontSize: 12,
                          }}>{e.author}</span>
                          <span style={{
                            background: "#1e1e2e", padding: "2px 6px", borderRadius: 4,
                            fontSize: 10, color: "#64748b",
                          }}>{e.entry_type}</span>
                          <span style={{
                            background: "#1e1e2e", padding: "2px 6px", borderRadius: 4,
                            fontSize: 10, color: "#8b5cf6",
                          }}>{e.phase}</span>
                        </div>
                        <span style={{ fontSize: 10, color: "#475569" }}>
                          {new Date(e.created_at).toLocaleString()}
                        </span>
                      </div>
                      <pre style={{
                        margin: 0, fontSize: 12, color: "#cbd5e1",
                        whiteSpace: "pre-wrap", wordBreak: "break-word",
                        maxHeight: 200, overflow: "auto",
                      }}>{e.content}</pre>
                    </div>
                  ))}
                  {(!detail.entries || detail.entries.length === 0) && (
                    <div style={{ color: "#475569", fontSize: 12, textAlign: "center", padding: 24 }}>
                      No entries yet. Start by adding the idea.
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* Export View */}
          {view === "export" && exportResult && (
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
                <h2 style={{ margin: 0, fontSize: 18 }}>📦 Claude Code Export</h2>
                <div style={{ display: "flex", gap: 8 }}>
                  <button onClick={() => { navigator.clipboard.writeText(exportResult); }} style={{
                    background: "linear-gradient(135deg, #10b981, #059669)",
                    border: "none", borderRadius: 6, color: "#fff",
                    padding: "8px 20px", fontSize: 12, cursor: "pointer",
                    fontFamily: "inherit", fontWeight: 600,
                  }}>📋 COPY TO CLIPBOARD</button>
                  <button onClick={() => setView("detail")} style={{
                    background: "#1e1e2e", border: "1px solid #2d2d44", borderRadius: 6,
                    color: "#94a3b8", padding: "8px 20px", fontSize: 12, cursor: "pointer",
                    fontFamily: "inherit",
                  }}>← BACK</button>
                </div>
              </div>
              <pre style={{
                background: "#13131f", border: "1px solid #1e1e2e", borderRadius: 12,
                padding: 24, fontSize: 13, color: "#cbd5e1",
                whiteSpace: "pre-wrap", wordBreak: "break-word",
                maxHeight: "70vh", overflow: "auto",
              }}>{exportResult}</pre>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
