import { useState, useRef, useEffect } from "react";
import { healthCheck, uploadDocument, queryRag } from "./api";
import "./App.css";

function App() {
  const [healthStatus, setHealthStatus] = useState("idle");
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [topK, setTopK] = useState(4);
  const [loadingQuery, setLoadingQuery] = useState(false);
  const [showSidebar, setShowSidebar] = useState(false);
  const [file, setFile] = useState(null);
  const [loadingUpload, setLoadingUpload] = useState(false);
  const [uploadMsg, setUploadMsg] = useState(null);
  const [showUploadPanel, setShowUploadPanel] = useState(false);
  const [uploadBtnAnim, setUploadBtnAnim] = useState(false);
  const [inputHover, setInputHover] = useState(false);
  const messagesEndRef = useRef(null);
  const fileInputRef = useRef(null);
  const uploadBtnRef = useRef(null);
  const uploadPanelRef = useRef(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
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

  // Close upload panel on Escape or click outside
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
      if (e.key === "Escape" && showUploadPanel) closeUploadPanel();
    }
    document.addEventListener("mousedown", handleClickOutside);
    document.addEventListener("keydown", handleEsc);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleEsc);
    };
  }, [showUploadPanel]);

  async function openUploadPanel() {
    setUploadBtnAnim(true);
    // Wait for expand animation
    await new Promise(r => setTimeout(r, 300));
    setUploadBtnAnim(false);
    setShowUploadPanel(true);
  }

  function closeUploadPanel() {
    setShowUploadPanel(false);
  }

  async function handleSend() {
    const text = input.trim();
    if (!text || loadingQuery) return;

    setInput("");

    const userMsg = { role: "user", content: text };
    setMessages((prev) => [...prev, userMsg]);

    setLoadingQuery(true);
    const placeholderId = Date.now();
    setMessages((prev) => [
      ...prev,
      { role: "assistant", content: "", sources: [], id: placeholderId, loading: true },
    ]);

    try {
      const data = await queryRag(text, topK);
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === placeholderId
            ? {
                ...msg,
                content: data.answer || "",
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
                content: err.response?.data?.detail || "查询失败，请检查后端服务是否正常。",
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
    if (!file) return;
    setLoadingUpload(true);
    setUploadMsg(null);
    try {
      await uploadDocument(file);
      setUploadMsg({ type: "success", text: `✅ ${file.name} 已上传并索引` });
      setFile(null);
      setTimeout(() => closeUploadPanel(), 1500);
    } catch (err) {
      setUploadMsg({
        type: "error",
        text: `❌ 上传失败：${err.response?.data?.detail || "未知错误"}`,
      });
    } finally {
      setLoadingUpload(false);
    }
  }

  function newChat() {
    setMessages([]);
  }

  function getRelevanceLabel(score) {
    const v = Number(score);
    if (isNaN(v)) return "Unknown";
    if (v >= 0.7) return "High";
    if (v >= 0.5) return "Medium";
    return "Low";
  }

  const statusConfig = {
    idle: { label: "Not Checked", color: "#6b7280" },
    checking: { label: "Checking...", color: "#f59e0b" },
    online: { label: "Online", color: "#22c55e" },
    offline: { label: "Offline", color: "#ef4444" },
  };

  return (
    <div className="chat-container">
      {/* Sidebar */}
      <aside className={`sidebar ${showSidebar ? "open" : ""}`}>
        <div className="sidebar-header">
          <div className="sidebar-logo">
            <span className="logo-icon">🧠</span>
            <span className="logo-text">Local RAG</span>
          </div>
        </div>

        <button className="new-chat-btn" onClick={newChat}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
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
            <span className="status-badge" style={{ color: statusConfig[healthStatus].color }}>
              <span className="status-dot" style={{ background: statusConfig[healthStatus].color }}></span>
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
            className={`upload-trigger-btn ${uploadBtnAnim ? "expanding" : ""}`}
            onClick={openUploadPanel}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
              <polyline points="17 8 12 3 7 8"></polyline>
              <line x1="12" y1="3" x2="12" y2="15"></line>
            </svg>
            Upload Document
          </button>
        </div>
      </aside>

      {/* Upload Modal Panel */}
      {showUploadPanel && (
        <div className="upload-modal-overlay">
          <div className="upload-modal" ref={uploadPanelRef}>
            <div className="upload-modal-header">
              <h2>Upload Document</h2>
              <button className="modal-close-btn" onClick={closeUploadPanel}>
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <line x1="18" y1="6" x2="6" y2="18"></line>
                  <line x1="6" y1="6" x2="18" y2="18"></line>
                </svg>
              </button>
            </div>

            <div
              className={`modal-upload-area ${file ? "has-file" : ""}`}
              onClick={() => fileInputRef.current?.click()}
            >
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf,.txt,.md"
                style={{ display: "none" }}
                onChange={(e) => setFile(e.target.files[0])}
              />
              {file ? (
                <>
                  <div className="modal-file-icon">📄</div>
                  <div className="modal-file-info">
                    <p className="modal-file-name">{file.name}</p>
                    <p className="modal-file-size">{(file.size / 1024).toFixed(1)} KB</p>
                  </div>
                  <button
                    className="modal-file-remove"
                    onClick={(e) => { e.stopPropagation(); setFile(null); }}
                  >
                    ✕
                  </button>
                </>
              ) : (
                <>
                  <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                    <polyline points="17 8 12 3 7 8"></polyline>
                    <line x1="12" y1="3" x2="12" y2="15"></line>
                  </svg>
                  <p className="modal-upload-text">Click to choose a file</p>
                  <p className="modal-upload-hint">PDF, TXT, Markdown supported</p>
                </>
              )}
            </div>

            <button
              className="modal-upload-btn"
              onClick={handleUpload}
              disabled={!file || loadingUpload}
            >
              {loadingUpload ? (
                <span className="modal-btn-loading">
                  <span className="modal-loader"></span>
                  Uploading...
                </span>
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

      {/* Main chat area */}
      <div className="main-area">
        {/* Top bar */}
        <header className="topbar">
          <button className="sidebar-toggle" onClick={() => setShowSidebar(!showSidebar)}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="3" y1="12" x2="21" y2="12"></line>
              <line x1="3" y1="6" x2="21" y2="6"></line>
              <line x1="3" y1="18" x2="21" y2="18"></line>
            </svg>
          </button>
          <div className="topbar-title">
            <span className="title-dot" style={{ background: statusConfig[healthStatus].color }}></span>
            Local RAG Chat
          </div>
          <button className="new-chat-btn-icon" onClick={newChat} title="New Chat">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="12" y1="5" x2="12" y2="19"></line>
              <line x1="5" y1="12" x2="19" y2="12"></line>
            </svg>
          </button>
        </header>

        {/* Messages */}
        <div className="messages-area">
          {messages.length === 0 && !loadingQuery && (
            <div className="welcome">
              <div className="welcome-icon">🧠</div>
              <h1 className="welcome-title">Local RAG Assistant</h1>
              <p className="welcome-desc">
                Upload documents to build your local knowledge base, then ask me anything!
              </p>
              <div className="welcome-hints">
                <div className="hint-item" onClick={() => { setInput("What documents are available?"); }}>
                  <span className="hint-icon">📄</span>
                  What documents are available?
                </div>
                <div className="hint-item" onClick={() => { setInput("Summarize the content of my documents."); }}>
                  <span className="hint-icon">📝</span>
                  Summarize the content
                </div>
                <div className="hint-item" onClick={() => { setInput("Explain the main topics covered."); }}>
                  <span className="hint-icon">🔍</span>
                  Explain the main topics
                </div>
              </div>
            </div>
          )}

          {messages.map((msg, idx) => (
            <div key={idx} className={`message ${msg.role}`}>
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
                    <div className="message-text">{msg.content}</div>
                    {msg.sources && msg.sources.length > 0 && (
                      <div className="message-sources">
                        <div className="sources-bar">
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <circle cx="12" cy="12" r="10"></circle>
                            <line x1="12" y1="16" x2="12" y2="12"></line>
                            <line x1="12" y1="8" x2="12.01" y2="8"></line>
                          </svg>
                          {msg.sources.length} source{msg.sources.length > 1 ? "s" : ""} retrieved
                        </div>
                        <div className="sources-list">
                          {msg.sources.map((source, si) => (
                            <div className="source-chip" key={si}>
                              <span className="source-label">
                                {source.source || source.filename || `Source ${si + 1}`}
                              </span>
                              {source.score !== undefined && (
                                <span className="source-score" style={{
                                  color: source.score >= 0.7 ? "#22c55e" : source.score >= 0.5 ? "#f59e0b" : "#ef4444",
                                }}>
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
          <div ref={messagesEndRef} />
        </div>

        {/* Input area with Apple AI hover glow */}
        <div className="input-area">
          <div
            className={`input-wrapper ${inputHover ? "glow" : ""}`}
            onMouseEnter={() => setInputHover(true)}
            onMouseLeave={() => setInputHover(false)}
          >
            <textarea
              className="chat-input"
              placeholder="Ask a question about your documents..."
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={loadingQuery}
              rows={1}
            />
            <button
              className="send-btn"
              onClick={handleSend}
              disabled={!input.trim() || loadingQuery}
            >
              {loadingQuery ? (
                <div className="send-loader"></div>
              ) : (
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <line x1="22" y1="2" x2="11" y2="13"></line>
                  <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
                </svg>
              )}
            </button>
          </div>
          <p className="input-footer">
            Local RAG System · Powered by Qwen3 + Qdrant
          </p>
        </div>
      </div>
    </div>
  );
}

export default App;