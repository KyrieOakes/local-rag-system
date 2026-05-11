import { useState, useRef, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import {
  healthCheck,
  uploadDocument,
  uploadDocuments,
  queryRag,
  listDocuments,
  deleteDocument,
} from "./api";
import "./App.css";

function App() {
  const [healthStatus, setHealthStatus] = useState("idle");
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [topK, setTopK] = useState(4);
  const [loadingQuery, setLoadingQuery] = useState(false);

  const [showSidebar, setShowSidebar] = useState(false);

  const [files, setFiles] = useState([]);
  const [loadingUpload, setLoadingUpload] = useState(false);
  const [uploadMsg, setUploadMsg] = useState(null);
  const [uploadResults, setUploadResults] = useState(null);
  const [showUploadPanel, setShowUploadPanel] = useState(false);
  const [uploadBtnAnim, setUploadBtnAnim] = useState(false);

  const [inputHover, setInputHover] = useState(false);

  const [showDocMgr, setShowDocMgr] = useState(false);
  const [docsList, setDocsList] = useState([]);
  const [docsLoading, setDocsLoading] = useState(false);
  const [docsError, setDocsError] = useState(null);
  const [deletingSource, setDeletingSource] = useState(null);
  const [deleteMsg, setDeleteMsg] = useState(null);

  const messagesEndRef = useRef(null);
  const fileInputRef = useRef(null);
  const uploadBtnRef = useRef(null);
  const uploadPanelRef = useRef(null);
  const docMgrPanelRef = useRef(null);

  const statusConfig = {
    idle: { label: "Not Checked", color: "#5c5b64" },
    checking: { label: "Checking…", color: "#fbbf24" },
    online: { label: "Connected", color: "#4ade80" },
    offline: { label: "Disconnected", color: "#f87171" },
  };

  useEffect(() => {
    if (messages.length === 0) return;

    messagesEndRef.current?.scrollIntoView({
      behavior: "smooth",
      block: "end",
    });
  }, [messages]);

  useEffect(() => {
    async function initCheck() {
      setHealthStatus("checking");
      try {
        await healthCheck();
        setHealthStatus("online");
      } catch {
        setHealthStatus("offline");
      }
    }

    initCheck();
  }, []);

  useEffect(() => {
    function handleClickOutside(e) {
      if (
        showUploadPanel &&
        uploadPanelRef.current &&
        !uploadPanelRef.current.contains(e.target) &&
        !uploadBtnRef.current?.contains(e.target)
      ) {
        closeUploadPanel();
      }
    }

    function handleEsc(e) {
      if (e.key === "Escape" && showUploadPanel) {
        closeUploadPanel();
      }
    }

    document.addEventListener("mousedown", handleClickOutside);
    document.addEventListener("keydown", handleEsc);

    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleEsc);
    };
  }, [showUploadPanel]);

  useEffect(() => {
    function handleClickOutside(e) {
      if (
        showDocMgr &&
        docMgrPanelRef.current &&
        !docMgrPanelRef.current.contains(e.target)
      ) {
        setShowDocMgr(false);
      }
    }

    function handleEsc(e) {
      if (e.key === "Escape" && showDocMgr) {
        setShowDocMgr(false);
      }
    }

    document.addEventListener("mousedown", handleClickOutside);
    document.addEventListener("keydown", handleEsc);

    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleEsc);
    };
  }, [showDocMgr]);

  async function openUploadPanel() {
    setUploadBtnAnim(true);
    await new Promise((resolve) => setTimeout(resolve, 300));
    setUploadBtnAnim(false);
    setShowUploadPanel(true);
  }

  function closeUploadPanel() {
    setShowUploadPanel(false);
    setUploadMsg(null);
    setFiles([]);
    setUploadResults(null);
  }

  async function openDocManager() {
    setShowDocMgr(true);
    setDocsLoading(true);
    setDocsError(null);
    setDeleteMsg(null);

    try {
      const docs = await listDocuments();
      setDocsList(Array.isArray(docs) ? docs : []);
    } catch (err) {
      setDocsError(
        err.response?.data?.detail || "Failed to load documents."
      );
      setDocsList([]);
    } finally {
      setDocsLoading(false);
    }
  }

  async function handleDeleteDoc(source) {
    if (!source || deletingSource) return;

    setDeletingSource(source);
    setDeleteMsg(null);

    try {
      await deleteDocument(source);

      setDeleteMsg({
        type: "success",
        text: `Deleted "${source}" successfully.`,
      });

      const docs = await listDocuments();
      setDocsList(Array.isArray(docs) ? docs : []);
    } catch (err) {
      setDeleteMsg({
        type: "error",
        text: `Failed to delete "${source}": ${
          err.response?.data?.detail || "Unknown error"
        }`,
      });
    } finally {
      setDeletingSource(null);
    }
  }

  function groupByType(docs) {
    const groups = {};

    for (const doc of docs) {
      const fileType = doc.file_type || "unknown";

      if (!groups[fileType]) {
        groups[fileType] = [];
      }

      groups[fileType].push(doc);
    }

    return groups;
  }

  async function handleSend() {
    const text = input.trim();

    if (!text || loadingQuery) return;

    setInput("");

    const userMsg = {
      role: "user",
      content: text,
    };

    setMessages((prev) => [...prev, userMsg]);

    setLoadingQuery(true);

    const placeholderId = Date.now();

    setMessages((prev) => [
      ...prev,
      {
        id: placeholderId,
        role: "assistant",
        content: "",
        sources: [],
        loading: true,
      },
    ]);

    try {
      const data = await queryRag(text, topK);

      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === placeholderId
            ? {
                ...msg,
                content: data.answer || "No answer returned.",
                sources: data.sources || [],
                loading: false,
              }
            : msg
        )
      );
    } catch (err) {
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === placeholderId
            ? {
                ...msg,
                content:
                  err.response?.data?.detail ||
                  "Query failed. Please check whether the backend service is running.",
                sources: [],
                loading: false,
              }
            : msg
        )
      );
    } finally {
      setLoadingQuery(false);
    }
  }

  function handleKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  async function handleHealthCheck() {
    setHealthStatus("checking");

    try {
      await healthCheck();
      setHealthStatus("online");
    } catch {
      setHealthStatus("offline");
    }
  }

  async function handleUpload() {
    if (files.length === 0 || loadingUpload) return;

    setLoadingUpload(true);
    setUploadMsg(null);
    setUploadResults(null);

    try {
      const data = await uploadDocuments(files);
      const results = data.results;

      setUploadResults(results);

      const succeeded = results.filter((r) => r.status === "indexed").length;
      const failed = results.filter((r) => r.status === "error").length;

      if (failed === 0) {
        setUploadMsg({
          type: "success",
          text: `${succeeded} file${succeeded !== 1 ? "s" : ""} uploaded and indexed successfully.`,
        });
      } else if (succeeded === 0) {
        setUploadMsg({
          type: "error",
          text: `All ${failed} file${failed !== 1 ? "s" : ""} failed.`,
        });
      } else {
        setUploadMsg({
          type: "partial",
          text: `${succeeded} indexed, ${failed} failed.`,
        });
      }
    } catch (err) {
      setUploadMsg({
        type: "error",
        text: `Upload failed: ${
          err.response?.data?.detail || "Unknown error"
        }`,
      });
    } finally {
      setLoadingUpload(false);
    }
  }

  function newChat() {
    setMessages([]);
    setInput("");
  }

  function fileTypeIcon(fileType) {
    if (fileType === ".pdf") return (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
        <polyline points="14 2 14 8 20 8"></polyline>
        <line x1="16" y1="13" x2="8" y2="13"></line>
        <line x1="16" y1="17" x2="8" y2="17"></line>
        <polyline points="10 9 9 9 8 9"></polyline>
      </svg>
    );
    if (fileType === ".txt") return (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
        <polyline points="14 2 14 8 20 8"></polyline>
        <line x1="16" y1="13" x2="8" y2="13"></line>
        <line x1="16" y1="17" x2="8" y2="17"></line>
      </svg>
    );
    if (fileType === ".md") return (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
        <polyline points="14 2 14 8 20 8"></polyline>
        <path d="M8 13h2l1 3 1-5 1 5 1-3h2"></path>
      </svg>
    );
    return (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path>
        <polyline points="13 2 13 9 20 9"></polyline>
      </svg>
    );
  }

  function getRelevanceLabel(score) {
    const value = Number(score);

    if (Number.isNaN(value)) return "Unknown";
    if (value >= 0.7) return "High";
    if (value >= 0.5) return "Medium";
    return "Low";
  }

  function getRelevanceColor(score) {
    const value = Number(score);

    if (Number.isNaN(value)) return "#9ca3af";
    if (value >= 0.7) return "#22c55e";
    if (value >= 0.5) return "#f59e0b";
    return "#ef4444";
  }

  function getFileResult(filename) {
    if (!Array.isArray(uploadResults)) return null;
    return uploadResults.find((r) => r.filename === filename) || null;
  }

  return (
    <div className="chat-container">
      <div className="noise-overlay"></div>

      <aside className={`sidebar ${showSidebar ? "open" : ""}`}>
        <div className="sidebar-header">
          <div className="sidebar-logo">
            <span className="logo-icon">🧠</span>
            <span className="logo-text">Local RAG</span>
          </div>
        </div>

        <button className="new-chat-btn" onClick={newChat}>
          <svg
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          >
            <line x1="12" y1="5" x2="12" y2="19"></line>
            <line x1="5" y1="12" x2="19" y2="12"></line>
          </svg>
          New Chat
        </button>

        <div className="sidebar-section">
          <div className="section-title">System</div>

          <button
            className={`sidebar-item health-item ${healthStatus}`}
            onClick={handleHealthCheck}
            disabled={healthStatus === "checking"}
          >
            <span className="item-label">Backend Status</span>
            <span
              className="status-badge"
              style={{ color: statusConfig[healthStatus].color }}
            >
              <span
                className="status-dot"
                style={{ background: statusConfig[healthStatus].color }}
              ></span>
              {statusConfig[healthStatus].label}
            </span>
          </button>

          <div className="sidebar-item">
            <span className="item-label">Top K</span>
            <div className="topk-control">
              <input
                type="range"
                min="1"
                max="10"
                value={topK}
                onChange={(e) => setTopK(Number(e.target.value))}
              />
              <span className="topk-value">{topK}</span>
            </div>
          </div>
        </div>

        <div className="sidebar-section">
          <div className="section-title">Upload Document</div>

          <button
            ref={uploadBtnRef}
            className={`upload-trigger-btn ${
              uploadBtnAnim ? "expanding" : ""
            }`}
            onClick={openUploadPanel}
          >
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
            >
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
              <polyline points="17 8 12 3 7 8"></polyline>
              <line x1="12" y1="3" x2="12" y2="15"></line>
            </svg>
            Upload Document
          </button>
        </div>

        <div className="sidebar-section">
          <div className="section-title">Manage Documents</div>

          <button className="docmgr-trigger-btn" onClick={openDocManager}>
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
            >
              <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path>
              <polyline points="13 2 13 9 20 9"></polyline>
            </svg>
            Browse & Delete
          </button>
        </div>
      </aside>

      {showUploadPanel && (
        <div className="upload-modal-overlay">
          <div className="upload-modal" ref={uploadPanelRef}>
            <div className="upload-modal-header">
              <h2>Upload Document</h2>

              <button className="modal-close-btn" onClick={closeUploadPanel}>
                <svg
                  width="20"
                  height="20"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                >
                  <line x1="18" y1="6" x2="6" y2="18"></line>
                  <line x1="6" y1="6" x2="18" y2="18"></line>
                </svg>
              </button>
            </div>

            <div
              className={`modal-upload-area ${files.length > 0 ? "has-files" : ""}`}
              onClick={() => fileInputRef.current?.click()}
            >
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf,.txt,.md"
                multiple
                style={{ display: "none" }}
                onChange={(e) => {
                  const selected = Array.from(e.target.files || []);
                  if (selected.length > 0) {
                    setFiles((prev) => [...prev, ...selected]);
                    setUploadMsg(null);
                    setUploadResults(null);
                  }
                  e.target.value = "";
                }}
              />

              {files.length > 0 ? (
                <div className="modal-upload-add-more">
                  <svg
                    width="20"
                    height="20"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.5"
                  >
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                    <polyline points="17 8 12 3 7 8"></polyline>
                    <line x1="12" y1="3" x2="12" y2="15"></line>
                  </svg>
                  <span>Click to add more files</span>
                </div>
              ) : (
                <>
                  <svg
                    width="32"
                    height="32"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.5"
                  >
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                    <polyline points="17 8 12 3 7 8"></polyline>
                    <line x1="12" y1="3" x2="12" y2="15"></line>
                  </svg>
                  <p className="modal-upload-text">Click to choose files</p>
                  <p className="modal-upload-hint">
                    PDF, TXT, and Markdown files are supported. Multiple files allowed.
                  </p>
                </>
              )}
            </div>

            {files.length > 0 && (
              <div className="modal-file-list">
                {files.map((f, idx) => {
                  const result = getFileResult(f.name);
                  return (
                    <div
                      key={`${f.name}-${idx}`}
                      className={`modal-file-row${
                        result
                          ? result.status === "indexed"
                            ? " success"
                            : " error"
                          : ""
                      }`}
                    >
                      <span className="modal-file-row-icon">
                        {fileTypeIcon(
                          f.name.slice(f.name.lastIndexOf("."))
                        )}
                      </span>
                      <div className="modal-file-row-info">
                        <p className="modal-file-row-name">{f.name}</p>
                        <p className="modal-file-row-size">
                          {(f.size / 1024).toFixed(1)} KB
                        </p>
                      </div>
                      {result ? (
                        <span
                          className={`modal-file-row-status ${
                            result.status === "indexed" ? "success" : "error"
                          }`}
                          title={
                            result.status === "error"
                              ? result.error
                              : `${result.chunks} chunks`
                          }
                        >
                          {result.status === "indexed" ? "✓" : "✗"}
                        </span>
                      ) : (
                        <button
                          className="modal-file-row-remove"
                          onClick={(e) => {
                            e.stopPropagation();
                            setFiles((prev) =>
                              prev.filter((_, i) => i !== idx)
                            );
                            setUploadMsg(null);
                            setUploadResults(null);
                          }}
                        >
                          ✕
                        </button>
                      )}
                    </div>
                  );
                })}
              </div>
            )}

            <button
              className="modal-upload-btn"
              onClick={handleUpload}
              disabled={files.length === 0 || loadingUpload}
            >
              {loadingUpload ? (
                <span className="modal-btn-loading">
                  <span className="modal-loader"></span>
                  Uploading...
                </span>
              ) : files.length > 0 ? (
                `Upload & Index ${files.length} File${
                  files.length !== 1 ? "s" : ""
                }`
              ) : (
                "Upload & Index"
              )}
            </button>

            {uploadMsg && (
              <div className={`modal-upload-msg ${uploadMsg.type}`}>
                {uploadMsg.text}
              </div>
            )}
          </div>
        </div>
      )}

      {showDocMgr && (
        <div className="upload-modal-overlay">
          <div className="upload-modal docmgr-modal" ref={docMgrPanelRef}>
            <div className="upload-modal-header">
              <h2>Document Manager</h2>

              <button
                className="modal-close-btn"
                onClick={() => setShowDocMgr(false)}
              >
                <svg
                  width="20"
                  height="20"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                >
                  <line x1="18" y1="6" x2="6" y2="18"></line>
                  <line x1="6" y1="6" x2="18" y2="18"></line>
                </svg>
              </button>
            </div>

            {docsLoading ? (
              <div className="docmgr-loading">
                <div className="typing-indicator">
                  <span></span>
                  <span></span>
                  <span></span>
                </div>
                <p>Loading documents...</p>
              </div>
            ) : docsError ? (
              <div className="docmgr-error">
                <p>{docsError}</p>

                <button className="docmgr-retry-btn" onClick={openDocManager}>
                  Retry
                </button>
              </div>
            ) : docsList.length === 0 ? (
              <div className="docmgr-empty">
                <div className="docmgr-empty-icon">
                  <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1" opacity="0.5">
                    <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" />
                    <polyline points="13 2 13 9 20 9" />
                  </svg>
                </div>
                <p>No documents indexed yet</p>
                <p className="docmgr-hint">
                  Use the Upload panel to add documents.
                </p>
              </div>
            ) : (
              <div className="docmgr-list">
                {Object.entries(groupByType(docsList)).map(([fileType, docs]) => (
                  <div key={fileType} className="docmgr-group">
                    <div className="docmgr-group-header">
                      <span className="docmgr-group-icon">
                        {fileTypeIcon(fileType)}
                      </span>
                      <span className="docmgr-group-type">{fileType}</span>
                      <span className="docmgr-group-count">
                        {docs.length} file{docs.length > 1 ? "s" : ""}
                      </span>
                    </div>

                    <div className="docmgr-group-files">
                      {docs.map((doc) => (
                        <div key={doc.source} className="docmgr-file-row">
                          <span
                            className="docmgr-file-name"
                            title={doc.source}
                          >
                            {doc.source}
                          </span>

                          <span className="docmgr-file-chunks">
                            {doc.chunks ?? 0} chunks
                          </span>

                          <button
                            className="docmgr-delete-btn"
                            onClick={() => handleDeleteDoc(doc.source)}
                            disabled={deletingSource === doc.source}
                            title={`Delete ${doc.source}`}
                          >
                            {deletingSource === doc.source ? (
                              <span className="docmgr-delete-loader"></span>
                            ) : (
                              <svg
                                width="16"
                                height="16"
                                viewBox="0 0 24 24"
                                fill="none"
                                stroke="currentColor"
                                strokeWidth="2"
                              >
                                <polyline points="3 6 5 6 21 6"></polyline>
                                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                              </svg>
                            )}
                          </button>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}

                {deleteMsg && (
                  <div className={`modal-upload-msg ${deleteMsg.type}`}>
                    {deleteMsg.text}
                  </div>
                )}
              </div>
            )}

            <button className="docmgr-refresh-btn" onClick={openDocManager}>
              <svg
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
              >
                <polyline points="23 4 23 10 17 10"></polyline>
                <polyline points="1 20 1 14 7 14"></polyline>
                <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
              </svg>
              Refresh
            </button>
          </div>
        </div>
      )}

      <main className="main-area">
        <header className="topbar">
          <button
            className="sidebar-toggle"
            onClick={() => setShowSidebar((prev) => !prev)}
          >
            <svg
              width="20"
              height="20"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <line x1="3" y1="12" x2="21" y2="12"></line>
              <line x1="3" y1="6" x2="21" y2="6"></line>
              <line x1="3" y1="18" x2="21" y2="18"></line>
            </svg>
          </button>

          <div className="topbar-title">
            <span
              className="title-dot"
              style={{ background: statusConfig[healthStatus].color }}
            ></span>
            Local RAG Chat
          </div>

          <button
            className="new-chat-btn-icon"
            onClick={newChat}
            title="New Chat"
          >
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <line x1="12" y1="5" x2="12" y2="19"></line>
              <line x1="5" y1="12" x2="19" y2="12"></line>
            </svg>
          </button>
        </header>

        <section className="messages-area">
          {messages.length === 0 && !loadingQuery && (
            <div className="welcome">
              <div className="welcome-icon">
                <svg width="48" height="48" viewBox="0 0 48 48" fill="none" stroke="currentColor" strokeWidth="1.2" opacity="0.9">
                  <circle cx="24" cy="24" r="20" stroke="rgba(167,139,250,0.25)" strokeWidth="2" />
                  <path d="M16 28c0-6 3-12 8-12s8 6 8 12" strokeLinecap="round" />
                  <path d="M18 24c0-3 2-7 6-7s6 4 6 7" strokeLinecap="round" />
                  <circle cx="20" cy="21" r="1.2" fill="currentColor" stroke="none" />
                  <circle cx="28" cy="21" r="1.2" fill="currentColor" stroke="none" />
                  <path d="M20 26c1.5 1.2 3.5 2 5.5 1.5" strokeLinecap="round" />
                  <line x1="16" y1="32" x2="32" y2="32" stroke="rgba(167,139,250,0.3)" strokeWidth="1" />
                  <line x1="18" y1="35" x2="30" y2="35" stroke="rgba(167,139,250,0.2)" strokeWidth="0.8" />
                </svg>
              </div>

              <h1 className="welcome-title">Local RAG Assistant</h1>

              <p className="welcome-desc">
                Upload documents to build your local knowledge base, then ask
                questions and get answers grounded in your own content.
              </p>

              <div className="welcome-hints">
                <div
                  className="hint-item"
                  onClick={() => setInput("What documents are available?")}
                >
                  <span className="hint-icon">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                      <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path>
                      <polyline points="13 2 13 9 20 9"></polyline>
                    </svg>
                  </span>
                  Browse available documents
                </div>

                <div
                  className="hint-item"
                  onClick={() =>
                    setInput("Summarize the key points from my documents.")
                  }
                >
                  <span className="hint-icon">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                      <line x1="8" y1="6" x2="21" y2="6"></line>
                      <line x1="8" y1="12" x2="21" y2="12"></line>
                      <line x1="8" y1="18" x2="21" y2="18"></line>
                      <line x1="3" y1="6" x2="3.01" y2="6"></line>
                      <line x1="3" y1="12" x2="3.01" y2="12"></line>
                      <line x1="3" y1="18" x2="3.01" y2="18"></line>
                    </svg>
                  </span>
                  Summarize the key points
                </div>

                <div
                  className="hint-item"
                  onClick={() =>
                    setInput("What are the main themes and topics covered?")
                  }
                >
                  <span className="hint-icon">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                      <circle cx="12" cy="12" r="10"></circle>
                      <line x1="12" y1="16" x2="12" y2="12"></line>
                      <line x1="12" y1="8" x2="12.01" y2="8"></line>
                    </svg>
                  </span>
                  Explore themes & topics
                </div>
              </div>
            </div>
          )}

          {messages.map((msg, index) => (
            <div
              key={msg.id || index}
              className={`message ${msg.role}`}
            >
              <div className="message-avatar">
                {msg.role === "user" ? "👤" : "🧠"}
              </div>

              <div className="message-content">
                {msg.loading ? (
                  <div className="typing-indicator">
                    <span></span>
                    <span></span>
                    <span></span>
                  </div>
                ) : (
                  <>
                    {msg.role === "assistant" ? (
                      <div className="message-text">
                        <ReactMarkdown>{msg.content}</ReactMarkdown>
                      </div>
                    ) : (
                      <div className="message-text">{msg.content}</div>
                    )}

                    {msg.sources && msg.sources.length > 0 && (
                      <div className="message-sources">
                        <div className="sources-bar">
                          <svg
                            width="14"
                            height="14"
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="2"
                          >
                            <circle cx="12" cy="12" r="10"></circle>
                            <line x1="12" y1="16" x2="12" y2="12"></line>
                            <line x1="12" y1="8" x2="12.01" y2="8"></line>
                          </svg>
                          {msg.sources.length} source
                          {msg.sources.length > 1 ? "s" : ""} retrieved
                        </div>

                        <div className="sources-list">
                          {msg.sources.map((source, sourceIndex) => (
                            <div className="source-chip" key={sourceIndex}>
                              <span className="source-label">
                                {source.source ||
                                  source.filename ||
                                  `Source ${sourceIndex + 1}`}
                              </span>

                              {source.score !== undefined && (
                                <span
                                  className="source-score"
                                  style={{
                                    color: getRelevanceColor(source.score),
                                  }}
                                  title={`Score: ${source.score}`}
                                >
                                  {getRelevanceLabel(source.score)}
                                </span>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </>
                )}
              </div>
            </div>
          ))}

          <div ref={messagesEndRef}></div>
        </section>

        <footer className="input-area">
          <div
            className={`input-wrapper ${
              inputHover || input.trim() ? "glow" : ""
            }`}
            onMouseEnter={() => setInputHover(true)}
            onMouseLeave={() => setInputHover(false)}
          >
            <textarea
              className="chat-input"
              value={input}
              placeholder="Ask your local knowledge base..."
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={loadingQuery}
              rows={1}
            />

            <button
              className="send-btn"
              onClick={handleSend}
              disabled={!input.trim() || loadingQuery}
              title="Send"
            >
              {loadingQuery ? (
                <span className="send-loader"></span>
              ) : (
                <svg
                  width="18"
                  height="18"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                >
                  <line x1="22" y1="2" x2="11" y2="13"></line>
                  <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
                </svg>
              )}
            </button>
          </div>

          <div className="input-footer">
            Press Enter to send, Shift + Enter for a new line.
          </div>
        </footer>
      </main>
    </div>
  );
}

export default App;