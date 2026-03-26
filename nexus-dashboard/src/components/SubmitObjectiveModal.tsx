import { useState, useCallback } from "react";
import { useDropzone } from "react-dropzone";
import { useObjectiveSubmit } from "../hooks/useObjectiveSubmit";

const ACCEPTED_TYPES: Record<string, string[]> = {
  "text/csv": [".csv", ".tsv"],
  "application/pdf": [".pdf"],
  "application/json": [".json"],
  "text/plain": [".txt", ".md"],
  "image/png": [".png"],
  "image/jpeg": [".jpg", ".jpeg"],
  "image/webp": [".webp"],
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"],
  "application/vnd.ms-excel": [".xls"],
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [".docx"],
};

const MAX_FILE_SIZE = 20 * 1024 * 1024; // 20MB
const MAX_FILES = 5;

interface Props {
  open: boolean;
  onClose: () => void;
}

export default function SubmitObjectiveModal({ open, onClose }: Props) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [objectiveType, setObjectiveType] = useState("strategic");
  const [priority, setPriority] = useState(5);
  const [files, setFiles] = useState<File[]>([]);
  const { state, submit, reset } = useObjectiveSubmit();

  const onDrop = useCallback(
    (accepted: File[]) => {
      setFiles((prev) => [...prev, ...accepted].slice(0, MAX_FILES));
    },
    [],
  );

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: ACCEPTED_TYPES,
    maxSize: MAX_FILE_SIZE,
    multiple: true,
    disabled: state.phase !== "idle",
  });

  const removeFile = (index: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== index));
  };

  const handleSubmit = async () => {
    if (!title.trim() || !description.trim()) return;
    await submit(title.trim(), description.trim(), objectiveType, priority, files);
  };

  const handleClose = () => {
    if (state.phase === "uploading" || state.phase === "submitting") return;
    reset();
    setTitle("");
    setDescription("");
    setObjectiveType("strategic");
    setPriority(5);
    setFiles([]);
    onClose();
  };

  if (!open) return null;

  const isSubmitting = state.phase === "uploading" || state.phase === "submitting";
  const canSubmit = title.trim().length > 0 && description.trim().length > 0 && !isSubmitting;

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 1000,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "rgba(0,0,0,0.65)",
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) handleClose();
      }}
    >
      <div
        style={{
          background: "#0f172a",
          border: "1px solid #334155",
          borderRadius: 16,
          width: "100%",
          maxWidth: 600,
          maxHeight: "90vh",
          overflow: "auto",
          padding: 28,
        }}
      >
        {/* Header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
          <div>
            <div style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: "0.14em", color: "#38bdf8" }}>
              New Objective
            </div>
            <h2 style={{ fontSize: 20, fontWeight: 700, marginTop: 4 }}>Submit Research Objective</h2>
          </div>
          <button
            onClick={handleClose}
            style={{
              background: "none",
              border: "none",
              color: "#94a3b8",
              fontSize: 22,
              cursor: "pointer",
              padding: 4,
            }}
          >
            x
          </button>
        </div>

        {/* Success state */}
        {state.phase === "success" && (
          <div style={{ textAlign: "center", padding: "32px 0" }}>
            <div style={{ fontSize: 18, fontWeight: 600, color: "#10b981", marginBottom: 12 }}>
              Objective Submitted
            </div>
            <div style={{ fontSize: 12, color: "#94a3b8", marginBottom: 20 }}>
              ID: {state.objectiveId}
            </div>
            <button
              onClick={handleClose}
              style={{
                background: "#38bdf8",
                color: "#0f172a",
                border: "none",
                borderRadius: 8,
                padding: "8px 20px",
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              Close
            </button>
          </div>
        )}

        {/* Error state */}
        {state.phase === "error" && (
          <div style={{ marginBottom: 16, padding: 12, background: "#1e1215", border: "1px solid #ef4444", borderRadius: 8 }}>
            <div style={{ color: "#ef4444", fontSize: 13, fontWeight: 600 }}>Error</div>
            <div style={{ color: "#fca5a5", fontSize: 12, marginTop: 4 }}>{state.error}</div>
          </div>
        )}

        {/* Form */}
        {state.phase !== "success" && (
          <>
            {/* Title */}
            <label style={{ display: "block", marginBottom: 14 }}>
              <div style={{ fontSize: 12, color: "#94a3b8", marginBottom: 6 }}>Title</div>
              <input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="e.g., Analyze differential gene expression in sepsis pathways"
                disabled={isSubmitting}
                style={{
                  width: "100%",
                  background: "#111827",
                  border: "1px solid #334155",
                  borderRadius: 8,
                  padding: "10px 12px",
                  color: "#e2e8f0",
                  fontSize: 14,
                  outline: "none",
                  boxSizing: "border-box",
                }}
              />
            </label>

            {/* Description */}
            <label style={{ display: "block", marginBottom: 14 }}>
              <div style={{ fontSize: 12, color: "#94a3b8", marginBottom: 6 }}>Description</div>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Detailed research question or objective description..."
                disabled={isSubmitting}
                rows={4}
                style={{
                  width: "100%",
                  background: "#111827",
                  border: "1px solid #334155",
                  borderRadius: 8,
                  padding: "10px 12px",
                  color: "#e2e8f0",
                  fontSize: 14,
                  outline: "none",
                  resize: "vertical",
                  boxSizing: "border-box",
                }}
              />
            </label>

            {/* Type + Priority row */}
            <div style={{ display: "flex", gap: 14, marginBottom: 14 }}>
              <label style={{ flex: 1 }}>
                <div style={{ fontSize: 12, color: "#94a3b8", marginBottom: 6 }}>Type</div>
                <select
                  value={objectiveType}
                  onChange={(e) => setObjectiveType(e.target.value)}
                  disabled={isSubmitting}
                  style={{
                    width: "100%",
                    background: "#111827",
                    border: "1px solid #334155",
                    borderRadius: 8,
                    padding: "10px 12px",
                    color: "#e2e8f0",
                    fontSize: 14,
                  }}
                >
                  <option value="strategic">Strategic</option>
                  <option value="tactical">Tactical</option>
                  <option value="exploratory">Exploratory</option>
                </select>
              </label>
              <label style={{ flex: 1 }}>
                <div style={{ fontSize: 12, color: "#94a3b8", marginBottom: 6 }}>
                  Priority: {priority}
                </div>
                <input
                  type="range"
                  min={1}
                  max={10}
                  value={priority}
                  onChange={(e) => setPriority(Number(e.target.value))}
                  disabled={isSubmitting}
                  style={{ width: "100%", marginTop: 6 }}
                />
              </label>
            </div>

            {/* File drop zone */}
            <div style={{ marginBottom: 18 }}>
              <div style={{ fontSize: 12, color: "#94a3b8", marginBottom: 6 }}>
                Context Files ({files.length}/{MAX_FILES})
              </div>
              <div
                {...getRootProps()}
                style={{
                  border: `2px dashed ${isDragActive ? "#38bdf8" : "#334155"}`,
                  borderRadius: 10,
                  padding: "20px 16px",
                  textAlign: "center",
                  cursor: isSubmitting ? "default" : "pointer",
                  background: isDragActive ? "#0f172a" : "#111827",
                  transition: "border-color 0.2s, background 0.2s",
                }}
              >
                <input {...getInputProps()} />
                <div style={{ color: "#94a3b8", fontSize: 13 }}>
                  {isDragActive
                    ? "Drop files here..."
                    : "Drag & drop files here, or click to browse"}
                </div>
                <div style={{ color: "#64748b", fontSize: 11, marginTop: 6 }}>
                  PDF, CSV, TXT, JSON, XLSX, DOCX, PNG, JPG, WebP (max 20MB each)
                </div>
              </div>

              {/* File list */}
              {files.length > 0 && (
                <div style={{ marginTop: 10 }}>
                  {files.map((f, i) => (
                    <div
                      key={i}
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                        padding: "6px 10px",
                        background: "#111827",
                        borderRadius: 6,
                        marginBottom: 4,
                      }}
                    >
                      <span style={{ fontSize: 12, color: "#e2e8f0" }}>
                        {f.name}{" "}
                        <span style={{ color: "#64748b" }}>
                          ({(f.size / 1024).toFixed(0)} KB)
                        </span>
                      </span>
                      {!isSubmitting && (
                        <button
                          onClick={() => removeFile(i)}
                          style={{
                            background: "none",
                            border: "none",
                            color: "#ef4444",
                            cursor: "pointer",
                            fontSize: 14,
                            padding: 2,
                          }}
                        >
                          x
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Progress bar */}
            {isSubmitting && (
              <div style={{ marginBottom: 16 }}>
                <div style={{ fontSize: 12, color: "#94a3b8", marginBottom: 6 }}>
                  {state.phase === "uploading"
                    ? `Uploading files... ${state.uploadProgress}%`
                    : "Submitting objective..."}
                </div>
                <div style={{ height: 6, background: "#1e293b", borderRadius: 999, overflow: "hidden" }}>
                  <div
                    style={{
                      width: `${state.phase === "submitting" ? 100 : state.uploadProgress}%`,
                      height: "100%",
                      background: state.phase === "submitting" ? "#10b981" : "#38bdf8",
                      transition: "width 0.3s",
                    }}
                  />
                </div>
              </div>
            )}

            {/* Submit button */}
            <button
              onClick={handleSubmit}
              disabled={!canSubmit}
              style={{
                width: "100%",
                padding: "12px 0",
                background: canSubmit ? "#38bdf8" : "#1e293b",
                color: canSubmit ? "#0f172a" : "#64748b",
                border: "none",
                borderRadius: 10,
                fontSize: 14,
                fontWeight: 700,
                cursor: canSubmit ? "pointer" : "default",
                transition: "background 0.2s",
              }}
            >
              {isSubmitting
                ? state.phase === "uploading"
                  ? "Uploading..."
                  : "Submitting..."
                : "Submit Objective"}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
