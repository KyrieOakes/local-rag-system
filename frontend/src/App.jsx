import { useState } from "react";
import { healthCheck, uploadDocument, queryRag } from "./api";
import "./App.css";

function App() {
  const [healthStatus, setHealthStatus] = useState("idle");

  const [file, setFile] = useState(null);
  const [uploadResult, setUploadResult] = useState(null);
  const [showUploadDetails, setShowUploadDetails] = useState(false);

  const [question, setQuestion] = useState("");
  const [topK, setTopK] = useState(4);
  const [answer, setAnswer] = useState("");
  const [sources, setSources] = useState([]);

  const [expandedSources, setExpandedSources] = useState({});

  const [loadingUpload, setLoadingUpload] = useState(false);
  const [loadingQuery, setLoadingQuery] = useState(false);

  async function handleHealthCheck() {
    setHealthStatus("checking");

    try {
      await healthCheck();
      setHealthStatus("online");
    } catch (err) {
      setHealthStatus("offline");
    }
  }

  async function handleUpload() {
    if (!file) return alert("请先选择文件");

    setLoadingUpload(true);
    setUploadResult(null);
    setShowUploadDetails(false);

    try {
      const data = await uploadDocument(file);
      setUploadResult(data);
    } catch (err) {
      setUploadResult({
        status: "failed",
        detail: err.response?.data?.detail || "上传失败",
      });
    } finally {
      setLoadingUpload(false);
    }
  }

  async function handleQuery() {
    if (!question.trim()) return alert("请输入问题");

    setLoadingQuery(true);
    setAnswer("");
    setSources([]);
    setExpandedSources({});

    try {
      const data = await queryRag(question, topK);
      setAnswer(data.answer || "");
      setSources(data.sources || []);
    } catch (err) {
      setAnswer(err.response?.data?.detail || "查询失败");
    } finally {
      setLoadingQuery(false);
    }
  }

  function toggleSource(index) {
    setExpandedSources((prev) => ({
      ...prev,
      [index]: !prev[index],
    }));
  }

  function getRelevanceLabel(score) {
    const value = Number(score);

    if (Number.isNaN(value)) return "Relevance unknown";
    if (value >= 0.7) return "High relevance";
    if (value >= 0.5) return "Medium relevance";
    return "Low relevance";
  }

  const statusText = {
    idle: "Not checked",
    checking: "Checking...",
    online: "Online",
    offline: "Offline",
  };

  const statusHint = {
    idle: "Click to check backend",
    checking: "Connecting to FastAPI",
    online: "Backend is reachable",
    offline: "Backend not reachable",
  };

  return (
    <div className="app-shell">
      <div className="gradient-bg gradient-one"></div>
      <div className="gradient-bg gradient-two"></div>

      <main className="page">
        <header className="hero">
          <div>
            <div className="eyebrow">Sprint 2 · Local Knowledge Base</div>
            <h1>Local RAG System</h1>
            <p className="subtitle">
              A clean testing console for document upload, vector retrieval,
              and local LLM-based question answering.
            </p>
          </div>

          <div className="hero-panel">
            <button
              className={`metric metric-clickable ${healthStatus}`}
              onClick={handleHealthCheck}
              disabled={healthStatus === "checking"}
            >
              <div>
                <span className="metric-label">Backend</span>
                <span className="metric-hint">{statusHint[healthStatus]}</span>
              </div>

              <span className={`status-pill ${healthStatus}`}>
                <span className="status-dot"></span>
                {statusText[healthStatus]}
              </span>
            </button>

            <div className="metric">
              <span className="metric-label">Top K</span>
              <span className="metric-value">{topK}</span>
            </div>

            <div className="metric">
              <span className="metric-label">Sources</span>
              <span className="metric-value">{sources.length}</span>
            </div>
          </div>
        </header>

        <section className="dashboard-grid single">
          <div className="card card-small">
            <div className="card-header">
              <div>
                <span className="section-number">01</span>
                <h2>Document Upload</h2>
              </div>

              <span className="file-badge">
                {file ? "File selected" : "No file"}
              </span>
            </div>

            <p className="card-desc">
              Upload PDF, TXT, or Markdown documents into the local RAG
              knowledge base.
            </p>

            <label className="upload-box">
              <input
                type="file"
                accept=".pdf,.txt,.md"
                disabled={loadingUpload}
                onChange={(e) => setFile(e.target.files[0])}
              />

              <div className="upload-icon">↥</div>

              <div>
                <p className="upload-title">
                  {file ? file.name : "Choose a document"}
                </p>
                <p className="upload-meta">
                  {file
                    ? `${(file.size / 1024).toFixed(2)} KB`
                    : "Supported: .pdf, .txt, .md"}
                </p>
              </div>
            </label>

            <button
              className="primary-btn"
              onClick={handleUpload}
              disabled={loadingUpload}
            >
              {loadingUpload ? "Uploading & Indexing..." : "Upload Document"}
            </button>

            {uploadResult && (
              <div className="result-panel">
                <button
                  className="toggle-row"
                  onClick={() => setShowUploadDetails(!showUploadDetails)}
                >
                  <div>
                    <span className="toggle-title">Upload Result</span>
                    <span className="toggle-desc">
                      {uploadResult.status === "indexed"
                        ? "Document has been indexed successfully"
                        : "Click to view processing details"}
                    </span>
                  </div>

                  <span className="toggle-arrow">
                    {showUploadDetails ? "−" : "+"}
                  </span>
                </button>

                {showUploadDetails && (
                  <div className="detail-grid">
                    {Object.entries(uploadResult).map(([key, value]) => (
                      <div className="detail-item" key={key}>
                        <span className="detail-key">{key}</span>
                        <span className="detail-value">{String(value)}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </section>

        <section className="card query-card">
          <div className="card-header">
            <div>
              <span className="section-number">02</span>
              <h2>RAG Question Answering</h2>
            </div>

            <div className="query-chip">
              Retrieval · Generation · Evidence
            </div>
          </div>

          <p className="card-desc">
            Ask a question based on the uploaded documents. The system retrieves
            relevant chunks and generates an answer using the local LLM.
          </p>

          <div className="query-layout">
            <div className={`query-input-panel ${loadingQuery ? "is-loading" : ""}`}>
              {loadingQuery && (
                <div className="query-overlay">
                  <div className="query-overlay-box">
                    <div className="loader"></div>
                    <div>
                      <p>Retrieving knowledge...</p>
                      <span>Searching sources and generating answer</span>
                    </div>
                  </div>
                </div>
              )}

              <textarea
                placeholder="Ask a question, e.g. What is this presentation about?"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                disabled={loadingQuery}
              />

              <div className="control-row">
                <div className="slider-group">
                  <div className="slider-header">
                    <label>Top K Retrieval</label>
                    <span>{topK}</span>
                  </div>

                  <input
                    className="range-input"
                    type="range"
                    min="1"
                    max="10"
                    value={topK}
                    disabled={loadingQuery}
                    onChange={(e) => setTopK(Number(e.target.value))}
                  />

                  <div className="range-labels">
                    <span>Precise</span>
                    <span>More context</span>
                  </div>
                </div>

                <button
                  className="ask-btn"
                  onClick={handleQuery}
                  disabled={loadingQuery}
                >
                  {loadingQuery ? "Generating..." : "Ask RAG"}
                </button>
              </div>
            </div>

            <div className="visual-panel">
              <div className="visual-card">
                <span className="visual-label">Pipeline</span>

                <div className="pipeline">
                  <div className="pipeline-step active">
                    <span>1</span>
                    Question
                  </div>

                  <div className="pipeline-line"></div>

                  <div className={`pipeline-step ${loadingQuery || answer ? "active" : ""}`}>
                    <span>2</span>
                    Retrieve
                  </div>

                  <div className="pipeline-line"></div>

                  <div className={`pipeline-step ${answer ? "active" : ""}`}>
                    <span>3</span>
                    Answer
                  </div>
                </div>
              </div>

              <div className="visual-card">
                <span className="visual-label">Current Retrieval Setting</span>

                <div className="topk-visual">
                  {Array.from({ length: 10 }).map((_, index) => (
                    <span
                      key={index}
                      className={index < topK ? "bar active" : "bar"}
                    ></span>
                  ))}
                </div>

                <p className="visual-note">
                  Higher Top K gives the model more document context, but may
                  include less relevant chunks.
                </p>
              </div>
            </div>
          </div>

          {loadingQuery && (
            <div className="loading-panel">
              <div className="loader"></div>
              <span>Retrieving relevant chunks and generating answer...</span>
            </div>
          )}

          {answer && !loadingQuery && (
            <div className="answer">
              <div className="answer-header">
                <h3>AI Answer</h3>
                <span>Generated from local knowledge base</span>
              </div>

              <p>{answer}</p>
            </div>
          )}

          {sources.length > 0 && (
            <div className="sources">
              <div className="sources-header">
                <h3>Retrieved Sources</h3>
                <span>{sources.length} evidence chunks</span>
              </div>

              <div className="source-list">
                {sources.map((source, index) => {
                  const isOpen = expandedSources[index];

                  return (
                    <div className="source" key={index}>
                      <button
                        className="source-summary"
                        onClick={() => toggleSource(index)}
                      >
                        <div className="source-main">
                          <div className="source-title-row">
                            <span className="source-title">
                              Source {index + 1}
                            </span>

                            {source.score !== undefined && (
                              <span className="score-pill">
                                {getRelevanceLabel(source.score)}
                              </span>
                            )}
                          </div>

                          <p className="source-file">
                            {source.source || source.filename || "unknown"}
                          </p>
                        </div>

                        <span className="source-arrow">
                          {isOpen ? "−" : "+"}
                        </span>
                      </button>

                      {isOpen && (
                        <div className="source-expanded">
                          <div className="source-content">
                            {source.content ||
                              source.page_content ||
                              JSON.stringify(source, null, 2)}
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </section>
      </main>
    </div>
  );
}

export default App;