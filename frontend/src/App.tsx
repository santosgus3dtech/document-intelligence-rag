import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import {
  ArrowRight,
  Check,
  ChevronLeft,
  ChevronRight,
  Download,
  FileImage,
  FileText,
  Files,
  LoaderCircle,
  Search,
  ShieldCheck,
  Upload,
  UserRound,
  X,
} from "lucide-react";
import { api, post } from "./api";
import type { Answer, Document, Mode, Passage, Session } from "./api";

type Panel = "documents" | "ask" | "source";
const examples = [
  {
    label: "Coolant filter",
    question: "How often should the coolant filter be replaced?",
  },
  {
    label: "Supplier inspection",
    question: "Quando ocorre a inspeção do fornecedor?",
  },
  {
    label: "Shift handover",
    question: "What is the scanner maintenance contact?",
  },
];
const errorMessage = (error: unknown) =>
  error instanceof Error
    ? error.message
    : "Something went wrong. Please try again.";
const sortDocuments = (items: Document[]) =>
  [...items].sort((left, right) => left.title.localeCompare(right.title));

export default function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [document, setDocument] = useState<Document | null>(null);
  const [page, setPage] = useState(1);
  const [highlight, setHighlight] = useState<Passage | null>(null);
  const [filter, setFilter] = useState("");
  const [mode, setMode] = useState<Mode>("hybrid");
  const [scope, setScope] = useState("all");
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [results, setResults] = useState<Passage[] | null>(null);
  const [task, setTask] = useState<"ask" | "search">("ask");
  const [panel, setPanel] = useState<Panel>("ask");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [sourceLoading, setSourceLoading] = useState(false);
  const [imageError, setImageError] = useState(false);
  const [imageVersion, setImageVersion] = useState(0);
  const [access, setAccess] = useState("public");
  const [showText, setShowText] = useState(false);
  const [zoom, setZoom] = useState(100);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const sessionEpoch = useRef(0);

  const refresh = useCallback(async () => {
    const epoch = sessionEpoch.current;
    const data = sortDocuments(await api<Document[]>("/documents"));
    if (epoch !== sessionEpoch.current) return [];
    setDocuments(data);
    setSelectedId((current) =>
      data.some((item) => item.id === current) ? current : (data[0]?.id ?? ""),
    );
    return data;
  }, []);

  useEffect(() => {
    let active = true;
    Promise.all([api<Session>("/session"), api<Document[]>("/documents")])
      .then(([user, items]) => {
        const docs = sortDocuments(items);
        if (active) {
          setSession(user);
          setDocuments(docs);
          setSelectedId(docs[0]?.id ?? "");
        }
      })
      .catch((err) => active && setError(errorMessage(err)))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, []);

  const processing = documents.some(
    (item) => item.status === "queued" || item.status === "processing",
  );
  useEffect(() => {
    if (!processing) return;
    const timer = window.setInterval(() => {
      refresh().catch((err) => setError(errorMessage(err)));
    }, 1800);
    return () => window.clearInterval(timer);
  }, [processing, refresh]);

  const selectedStatus = documents.find(
    (item) => item.id === selectedId,
  )?.status;
  useEffect(() => {
    const controller = new AbortController();
    const epoch = sessionEpoch.current;
    setDocument(null);
    setImageError(false);
    if (!selectedId) {
      setSourceLoading(false);
      return;
    }
    setSourceLoading(true);
    api<Document>(`/documents/${selectedId}`, { signal: controller.signal })
      .then((data) => {
        if (epoch === sessionEpoch.current) setDocument(data);
      })
      .catch((err) => {
        if (!controller.signal.aborted) setError(errorMessage(err));
      })
      .finally(() => {
        if (!controller.signal.aborted) setSourceLoading(false);
      });
    return () => controller.abort();
  }, [selectedId, selectedStatus, imageVersion]);

  function inspect(hit: Passage) {
    setSelectedId(hit.document_id);
    setPage(hit.page);
    setHighlight(hit);
    setPanel("source");
    setShowText(false);
    setImageError(false);
  }
  function selectDocument(item: Document) {
    setSelectedId(item.id);
    setPage(1);
    setHighlight(null);
    setPanel("source");
    setShowText(false);
    setImageError(false);
  }
  async function seed() {
    setBusy("seed");
    setError("");
    try {
      await post("/demo/seed", {});
      await refresh();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy("");
    }
  }
  async function upload(file?: File) {
    if (!file) return;
    setBusy("upload");
    setError("");
    try {
      if (file.size > 10 * 1024 * 1024)
        throw new Error("The upload exceeds the 10 MiB limit.");
      const body = new FormData();
      body.append("file", file);
      body.append("access", access);
      const result = await api<Document>("/documents", {
        method: "POST",
        body,
      });
      await refresh();
      setSelectedId(result.id);
      setPage(1);
      setHighlight(null);
      setPanel("source");
    } catch (err) {
      setError(errorMessage(err));
      setPanel("ask");
    } finally {
      setBusy("");
    }
  }
  async function switchIdentity(identity: string) {
    sessionEpoch.current += 1;
    setBusy("identity");
    setError("");
    setAnswer(null);
    setResults(null);
    setSubmitted("");
    setHighlight(null);
    setDocument(null);
    setDocuments([]);
    setSelectedId("");
    setAccess("public");
    setPage(1);
    try {
      setSession(await post<Session>("/demo/session", { identity }));
      await refresh();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy("");
    }
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (query.trim().length < 2 || busy) return;
    const epoch = sessionEpoch.current;
    setBusy(task);
    setError("");
    setSubmitted(query.trim());
    setAnswer(null);
    setResults(null);
    setHighlight(null);
    setPanel("ask");
    const shared = {
      mode,
      document_ids: scope === "selected" && selectedId ? [selectedId] : null,
    };
    try {
      if (task === "ask") {
        const data = await post<Answer>("/ask", {
          ...shared,
          question: query.trim(),
        });
        if (epoch === sessionEpoch.current) {
          setAnswer(data);
          if (data.citations[0]) inspect(data.citations[0]);
          setPanel("ask");
        }
      } else {
        const data = await post<{ results: Passage[] }>("/search", {
          ...shared,
          query: query.trim(),
        });
        if (epoch === sessionEpoch.current) setResults(data.results);
      }
    } catch (err) {
      if (epoch === sessionEpoch.current) setError(errorMessage(err));
    } finally {
      if (epoch === sessionEpoch.current) setBusy("");
    }
  }
  const visibleDocuments = documents.filter((item) =>
    `${item.title} ${item.filename}`
      .toLowerCase()
      .includes(filter.toLowerCase()),
  );
  const currentHighlight =
    highlight?.document_id === selectedId && highlight.page === page
      ? highlight
      : null;
  const titleFor = (hit: Passage) =>
    documents.find((item) => item.id === hit.document_id)?.title ??
    hit.title ??
    "Source document";
  const currentPassages =
    document?.passages?.filter((item) => item.page === page) ?? [];

  function citation(hit: Passage, index: number) {
    return (
      <button className="citation" key={hit.id} onClick={() => inspect(hit)}>
        <span className="citation-heading">
          <FileText size={23} />
          <span>
            <strong>
              [{index + 1}] {titleFor(hit)}
            </strong>
            <small>
              Page {hit.page} ·{" "}
              {hit.kind === "table" ? "Extracted table" : "Source passage"}
            </small>
          </span>
          <span className="inspect-label">
            Inspect source <ArrowRight size={17} />
          </span>
        </span>
        <span className="quote">“{hit.quote ?? hit.text}”</span>
      </button>
    );
  }

  return (
    <>
      <header className="app-header">
        <div className="brand">
          <Files size={27} strokeWidth={1.6} />
          <span>Document Intelligence</span>
        </div>
        <div className="session">
          <span className="local-indicator">
            <i />
            {session?.demo ? "Local demo" : "Authenticated API"}
          </span>
          <div className="identity">
            <UserRound size={24} />
            {session?.demo ? (
              <select
                aria-label="Demo identity"
                value={session.identity}
                disabled={!!busy}
                onChange={(event) => switchIdentity(event.target.value)}
              >
                <option value="viewer">Viewer</option>
                <option value="reviewer">Reviewer</option>
              </select>
            ) : (
              <span>{session?.identity ?? "Connecting…"}</span>
            )}
          </div>
        </div>
      </header>
      <nav className="mobile-nav" aria-label="Workspace panels">
        {(["documents", "ask", "source"] as const).map((name) => (
          <button
            key={name}
            className={panel === name ? "active" : ""}
            onClick={() => setPanel(name)}
          >
            {name === "ask"
              ? "Ask & search"
              : name[0].toUpperCase() + name.slice(1)}
          </button>
        ))}
      </nav>
      <main className="workspace">
        <aside
          className={`library panel ${panel === "documents" ? "mobile-active" : ""}`}
          aria-label="Document library"
        >
          <h2>
            Documents <span className="count">{documents.length}</span>
          </h2>
          <label
            className={`upload-button ${busy || !session?.can_upload ? "disabled" : ""}`}
          >
            <Upload size={18} />
            {busy === "upload" ? "Validating upload…" : "Upload document"}
            <input
              aria-label="Upload document"
              type="file"
              accept=".pdf,.png,.jpg,.jpeg"
              disabled={!!busy || !session?.can_upload}
              onChange={(event) => {
                upload(event.target.files?.[0]);
                event.target.value = "";
              }}
            />
          </label>
          {session?.can_restricted && (
            <label className="access-label">
              Upload access
              <select
                aria-label="Upload access"
                value={access}
                onChange={(event) => setAccess(event.target.value)}
              >
                <option value="public">Public workspace</option>
                <option value="restricted">Restricted</option>
              </select>
            </label>
          )}
          {session?.demo && (
            <button className="seed-button" onClick={seed} disabled={!!busy}>
              {busy === "seed"
                ? "Loading demo documents…"
                : "Load demo documents"}
            </button>
          )}
          <label className="filter">
            <Search size={17} />
            <input
              aria-label="Filter documents"
              placeholder="Filter documents"
              value={filter}
              onChange={(event) => setFilter(event.target.value)}
            />
          </label>
          <div className="document-list" aria-live="polite">
            {loading ? (
              <div className="small-state">
                <LoaderCircle className="spin" size={20} />
                Connecting to the library…
              </div>
            ) : visibleDocuments.length === 0 ? (
              <div className="small-state">
                <Files size={28} />
                <strong>
                  {filter ? "No matching documents" : "Your library is ready"}
                </strong>
                <span>
                  {filter
                    ? "Try another document name."
                    : "Upload a document or load the synthetic demo to begin."}
                </span>
              </div>
            ) : (
              visibleDocuments.map((item) => (
                <button
                  key={item.id}
                  className={`document-row ${selectedId === item.id ? "selected" : ""}`}
                  onClick={() => selectDocument(item)}
                >
                  {item.filename.endsWith(".pdf") ? (
                    <FileText className="file-icon" size={23} />
                  ) : (
                    <FileImage className="file-icon image-icon" size={23} />
                  )}
                  <span>
                    <strong>{item.title}</strong>
                    <small>
                      {item.filename.endsWith(".pdf") ? "PDF" : "Image"} ·{" "}
                      {item.page_count || "—"}{" "}
                      {item.page_count === 1 ? "page" : "pages"}
                      {item.access === "restricted" && (
                        <ShieldCheck size={12} aria-label="Restricted" />
                      )}
                    </small>
                    <small className={`status ${item.status}`}>
                      <i />
                      {item.status[0].toUpperCase() + item.status.slice(1)}
                    </small>
                  </span>
                </button>
              ))
            )}
          </div>
          <p className="library-footer">
            PDF, PNG or JPEG · up to 10 MB
            <br />
            <span>
              {session?.demo
                ? "Synthetic demo · identities are switchable"
                : "Permissions enforced by the server"}
            </span>
          </p>
        </aside>

        <section
          className={`conversation panel ${panel === "ask" ? "mobile-active" : ""}`}
          aria-label="Ask and search documents"
        >
          <div className="conversation-header">
            <h1>Ask your documents</h1>
            <p>Answers connected to their source.</p>
          </div>
          {error && (
            <div className="error-banner" role="alert">
              <span>{error}</span>
              <button aria-label="Dismiss error" onClick={() => setError("")}>
                <X size={17} />
              </button>
            </div>
          )}
          <div className="tool-row">
            <div className="mode-switch" aria-label="Retrieval mode">
              {(["hybrid", "lexical", "vector"] as const).map((value) => (
                <button
                  key={value}
                  disabled={!!busy}
                  aria-pressed={mode === value}
                  className={mode === value ? "active" : ""}
                  onClick={() => setMode(value)}
                >
                  {value[0].toUpperCase() + value.slice(1)}
                </button>
              ))}
            </div>
            <select
              disabled={!!busy}
              aria-label="Document scope"
              value={scope}
              onChange={(event) => setScope(event.target.value)}
            >
              <option value="all">All accessible documents</option>
              <option value="selected" disabled={!selectedId}>
                Selected document
              </option>
            </select>
          </div>
          <div
            className="task-switch"
            role="tablist"
            aria-label="Workspace task"
          >
            <button
              role="tab"
              disabled={!!busy}
              aria-selected={task === "ask"}
              onClick={() => {
                setTask("ask");
                setResults(null);
                setSubmitted("");
              }}
            >
              Ask a question
            </button>
            <button
              role="tab"
              disabled={!!busy}
              aria-selected={task === "search"}
              onClick={() => {
                setTask("search");
                setAnswer(null);
                setSubmitted("");
              }}
            >
              Search passages
            </button>
          </div>
          <div
            className="answer-area"
            aria-live="polite"
            aria-busy={busy === "ask" || busy === "search"}
          >
            {submitted && <p className="user-query">{submitted}</p>}
            {busy === "ask" || busy === "search" ? (
              <div className="answer-state">
                <LoaderCircle size={21} className="spin" />
                <span>Finding evidence in your accessible documents…</span>
              </div>
            ) : answer ? (
              <div className="answer-result">
                <h2>
                  {answer.status === "answered" ? (
                    <span className="check-icon">
                      <Check size={20} />
                    </span>
                  ) : (
                    <Search size={24} />
                  )}
                  {answer.status === "answered"
                    ? "Evidence found"
                    : "Insufficient evidence"}
                </h2>
                <p className="answer-copy">{answer.answer}</p>
                {answer.citations.map(citation)}
                <p className="answer-limits">{answer.limitations}</p>
              </div>
            ) : results ? (
              <div className="search-results">
                <h2>
                  {results.length
                    ? `${results.length} source passages`
                    : "No matching passages"}
                </h2>
                {results.length ? (
                  results.map(citation)
                ) : (
                  <p>Try a more specific term or upload a relevant document.</p>
                )}
              </div>
            ) : (
              <div className="welcome">
                <Files size={34} strokeWidth={1.2} />
                <h2>Start with a source.</h2>
                <p>
                  {documents.length
                    ? "Ask a question in English or Portuguese, then follow its citation back to the page."
                    : "Load the synthetic demo or upload a document. Your evidence will appear here."}
                </p>
              </div>
            )}
          </div>
          <div className="composer-area">
            <p className="suggestion-label">Try another question</p>
            <div className="suggestions">
              {examples.map((example) => (
                <button
                  key={example.label}
                  disabled={!!busy}
                  onClick={() => {
                    setTask("ask");
                    setQuery(example.question);
                    inputRef.current?.focus();
                  }}
                >
                  {example.label}
                </button>
              ))}
            </div>
            <form className="composer" onSubmit={submit}>
              <textarea
                ref={inputRef}
                aria-label={task === "ask" ? "Question" : "Search query"}
                placeholder={
                  task === "ask"
                    ? "Ask a question about your documents…"
                    : "Search for a passage…"
                }
                value={query}
                maxLength={1000}
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    event.currentTarget.form?.requestSubmit();
                  }
                }}
                rows={2}
              />
              <button
                type="submit"
                aria-label={task === "ask" ? "Ask" : "Search"}
                disabled={
                  !!busy ||
                  query.trim().length < 2 ||
                  !documents.some((item) => item.status === "ready")
                }
              >
                {busy === "ask" || busy === "search" ? (
                  <LoaderCircle size={18} className="spin" />
                ) : task === "ask" ? (
                  "Ask"
                ) : (
                  <Search size={20} />
                )}
              </button>
            </form>
            <p className="privacy-note">
              Local extractive answers. No document content leaves this server.
              <br />
              <span>
                Vector search uses local feature hashing; semantic models are
                not loaded.
              </span>
            </p>
          </div>
        </section>

        <section
          className={`source-panel panel ${panel === "source" ? "mobile-active" : ""}`}
          aria-label="Source inspector"
        >
          <header className="source-header">
            <div>
              <span>Source</span>
              <h2 title={document?.title}>
                {document?.title ?? "Document inspector"}
              </h2>
            </div>
            <div className="page-controls">
              <button
                aria-label="Previous page"
                disabled={page <= 1}
                onClick={() => {
                  setPage((current) => current - 1);
                  setImageError(false);
                }}
              >
                <ChevronLeft size={18} />
              </button>
              <span>
                {document?.page_count
                  ? `${page} / ${document.page_count}`
                  : "— / —"}
              </span>
              <button
                aria-label="Next page"
                disabled={!document?.page_count || page >= document.page_count}
                onClick={() => {
                  setPage((current) => current + 1);
                  setImageError(false);
                }}
              >
                <ChevronRight size={18} />
              </button>
              {document?.status === "ready" && (
                <a
                  aria-label="Download original source"
                  href={`/api/documents/${document.id}/source`}
                >
                  <Download size={20} />
                </a>
              )}
            </div>
          </header>
          <div className="source-tabs">
            <button aria-pressed={!showText} onClick={() => setShowText(false)}>
              Original page
            </button>
            <button aria-pressed={showText} onClick={() => setShowText(true)}>
              Extracted text & tables
            </button>
            <select
              aria-label="Page zoom"
              value={zoom}
              onChange={(event) => setZoom(Number(event.target.value))}
            >
              <option value={100}>100%</option>
              <option value={150}>150%</option>
              <option value={200}>200%</option>
            </select>
          </div>
          <div className="page-canvas">
            {sourceLoading ? (
              <div className="source-state">
                <LoaderCircle className="spin" size={27} />
                Loading source…
              </div>
            ) : !document ? (
              <div className="source-state">
                <FileText size={38} strokeWidth={1.3} />
                <h3>Inspect the evidence</h3>
                <p>Select a document or a citation to open its source.</p>
              </div>
            ) : document.status !== "ready" ? (
              <div className="source-state">
                {document.status === "failed" ? (
                  <>
                    <X size={28} />
                    <h3>Processing failed</h3>
                    <p>
                      {document.error ||
                        "The document could not be extracted. Try a clearer source."}
                    </p>
                  </>
                ) : (
                  <>
                    <LoaderCircle size={28} className="spin" />
                    <h3>
                      {document.status === "queued"
                        ? "Waiting to process"
                        : "Processing document"}
                    </h3>
                    <p>Extracting text, tables and source coordinates…</p>
                  </>
                )}
              </div>
            ) : showText ? (
              <div className="extracted-text">
                {currentPassages.length ? (
                  currentPassages.map((item) => (
                    <button
                      className={`text-block ${currentHighlight?.id === item.id ? "active" : ""}`}
                      key={item.id}
                      onClick={() => {
                        setHighlight(item);
                        setShowText(false);
                      }}
                    >
                      <small>
                        {item.kind.toUpperCase()} ·{" "}
                        {item.engine ?? document.engine} · Page {item.page}
                      </small>
                      {item.rows ? (
                        <table>
                          <tbody>
                            {item.rows.map((row, index) => (
                              <tr key={index}>
                                {row.map((cell, cellIndex) => (
                                  <td key={cellIndex}>{cell}</td>
                                ))}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      ) : (
                        <span>{item.text}</span>
                      )}
                    </button>
                  ))
                ) : (
                  <p>No readable text was found on this page.</p>
                )}
              </div>
            ) : imageError ? (
              <div className="source-state" role="alert">
                <p>The source preview could not be loaded.</p>
                <button
                  onClick={() => {
                    setImageError(false);
                    setImageVersion((value) => value + 1);
                  }}
                >
                  Retry source
                </button>
              </div>
            ) : (
              <div
                className="document-page"
                style={{
                  width: `${zoom}%`,
                  maxWidth: zoom === 100 ? 620 : "none",
                }}
              >
                <img
                  src={`/api/documents/${document.id}/pages/${page}?v=${imageVersion}`}
                  alt={`${document.title}, page ${page}`}
                  onError={() => setImageError(true)}
                />
                {currentHighlight && (
                  <div
                    className="source-highlight"
                    aria-label={`Highlighted evidence on page ${page}`}
                    style={{
                      left: `${currentHighlight.bbox[0] * 100}%`,
                      top: `${currentHighlight.bbox[1] * 100}%`,
                      width: `${(currentHighlight.bbox[2] - currentHighlight.bbox[0]) * 100}%`,
                      height: `${(currentHighlight.bbox[3] - currentHighlight.bbox[1]) * 100}%`,
                    }}
                  />
                )}
              </div>
            )}
          </div>
          {currentHighlight && (
            <div className="source-evidence">
              <strong>Highlighted evidence · page {page}</strong>
              <p>“{currentHighlight.quote ?? currentHighlight.text}”</p>
            </div>
          )}
          {(document?.warnings?.length ?? 0) > 0 && (
            <details className="extraction-notes">
              <summary>Extraction notes ({document!.warnings!.length})</summary>
              {document!.warnings!.map((note) => (
                <p key={note}>{note}</p>
              ))}
            </details>
          )}
        </section>
      </main>
    </>
  );
}
