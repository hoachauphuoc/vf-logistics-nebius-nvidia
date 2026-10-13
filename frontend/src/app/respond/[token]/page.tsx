"use client";

import { FileUp, Loader2, CheckCircle, XCircle, AlertTriangle } from "lucide-react";
import { useParams } from "next/navigation";
import { useCallback, useRef, useState } from "react";

const API_BASE = "/api/proxy";

type UploadState = "idle" | "uploading" | "success" | "blocked" | "error";

export default function RespondPage() {
  const params = useParams();
  const token = typeof params.token === "string" ? params.token : "";
  const fileRef = useRef<HTMLInputElement>(null);
  const [state, setState] = useState<UploadState>("idle");
  const [file, setFile] = useState<File | null>(null);
  const [message, setMessage] = useState("");
  const [dragOver, setDragOver] = useState(false);

  const upload = useCallback(async () => {
    if (!file || !token) return;
    setState("uploading");
    setMessage("");
    try {
      const formData = new FormData();
      formData.append("file", file);
      const res = await fetch(`${API_BASE}/evidence/respond`, {
        method: "POST",
        headers: { "X-VF-Evidence-Token": token },
        body: formData,
      });
      const body = await res.json().catch(() => null);
      if (res.ok && body?.received) {
        setState(body.blocked ? "blocked" : "success");
        setMessage(
          body.blocked
            ? "The file was received but flagged by our safety screen. A reviewer will follow up."
            : `Document received (version ${body.evidence_version ?? "?"}).`,
        );
      } else {
        setState("error");
        setMessage(body?.message || body?.error || `Upload failed (${res.status}).`);
      }
    } catch (err) {
      setState("error");
      setMessage(err instanceof Error ? err.message : "Network error.");
    }
  }, [file, token]);

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const f = e.dataTransfer.files[0];
    if (f) { setFile(f); setState("idle"); setMessage(""); }
  }, []);

  const onFileChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) { setFile(f); setState("idle"); setMessage(""); }
  }, []);

  return (
    <div className="flex min-h-screen items-center justify-center bg-black p-4">
      <div className="w-full max-w-md space-y-6">
        <div className="text-center">
          <h1 className="text-xl font-semibold text-white">Floorline</h1>
          <p className="mt-1 text-sm text-white/60">Submit evidence for your shipment</p>
        </div>

        <div className="rounded-xl border border-white/10 bg-white/[0.03] p-6 space-y-4">
          {!token ? (
            <div className="flex items-center gap-2 text-risk-critical text-sm">
              <XCircle className="size-4 shrink-0" />
              <p>No token found in the URL. Use the link your reviewer sent you.</p>
            </div>
          ) : (
            <>
              <div
                onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
                onDragLeave={() => setDragOver(false)}
                onDrop={onDrop}
                onClick={() => fileRef.current?.click()}
                className={`cursor-pointer rounded-lg border-2 border-dashed p-8 text-center transition-colors ${
                  dragOver ? "border-brand bg-brand/10" : "border-white/15 hover:border-white/30"
                }`}
              >
                <FileUp className="mx-auto size-8 text-white/40" />
                <p className="mt-2 text-sm text-white/70">
                  {file ? file.name : "Drop a file here or click to choose"}
                </p>
                <p className="mt-1 text-xs text-white/40">PDF, PNG, JPG, TIFF. Max 20 MB.</p>
                <input
                  ref={fileRef}
                  type="file"
                  accept=".pdf,.png,.jpg,.jpeg,.tiff,.tif"
                  className="hidden"
                  onChange={onFileChange}
                />
              </div>

              {file && state === "idle" && (
                <button
                  onClick={upload}
                  className="w-full rounded-lg bg-brand px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-brand/90"
                >
                  Upload {file.name}
                </button>
              )}

              {state === "uploading" && (
                <div className="flex items-center justify-center gap-2 py-3 text-sm text-white/70">
                  <Loader2 className="size-4 animate-spin" />
                  Uploading...
                </div>
              )}

              {state === "success" && (
                <div className="flex items-start gap-2 rounded-lg border border-risk-clear/30 bg-risk-clear/[0.07] p-3 text-sm text-risk-clear">
                  <CheckCircle className="mt-0.5 size-4 shrink-0" />
                  <p>{message}</p>
                </div>
              )}

              {state === "blocked" && (
                <div className="flex items-start gap-2 rounded-lg border border-risk-warn/30 bg-risk-warn/[0.07] p-3 text-sm text-risk-warn">
                  <AlertTriangle className="mt-0.5 size-4 shrink-0" />
                  <p>{message}</p>
                </div>
              )}

              {state === "error" && (
                <div className="flex items-start gap-2 rounded-lg border border-risk-critical/30 bg-risk-critical/[0.07] p-3 text-sm text-risk-critical">
                  <XCircle className="mt-0.5 size-4 shrink-0" />
                  <p>{message}</p>
                </div>
              )}

              {(state === "success" || state === "error" || state === "blocked") && (
                <button
                  onClick={() => { setFile(null); setState("idle"); setMessage(""); }}
                  className="w-full rounded-lg border border-white/15 px-4 py-2 text-sm text-white/70 transition-colors hover:border-white/30"
                >
                  Upload another document
                </button>
              )}
            </>
          )}
        </div>

        <p className="text-center text-xs text-white/30">
          This link is single-use per document type and expires after 7 days.
        </p>
      </div>
    </div>
  );
}
