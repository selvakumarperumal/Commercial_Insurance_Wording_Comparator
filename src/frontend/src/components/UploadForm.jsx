import { useRef, useState } from "react";
import { api } from "../api.js";
import { displayName, formatSize } from "../format.js";
import { Icon } from "./Icons.jsx";

function isPdf(file) {
  return file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
}

export default function UploadForm({ onCreated }) {
  const [pdfA, setPdfA] = useState(null);
  const [pdfB, setPdfB] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const form = useRef(null);

  function choose(setFile) {
    return (file) => {
      if (!file) return;
      if (!isPdf(file)) {
        setError(`${file.name} is not a PDF.`);
        return;
      }
      setError("");
      setFile(file);
    };
  }

  async function submit(event) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      const job = await api.createJob(pdfA, pdfB);
      form.current.reset();
      setPdfA(null);
      setPdfB(null);
      onCreated(job.job_id);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form ref={form} className="panel upload" onSubmit={submit}>
      <h2 className="panel-title">New comparison</h2>
      <DropSlot tag="A" file={pdfA} onFile={choose(setPdfA)} />
      <DropSlot tag="B" file={pdfB} onFile={choose(setPdfB)} />
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      <button className="primary block" disabled={busy || !pdfA || !pdfB}>
        {busy ? "Uploading…" : "Compare policies"}
      </button>
    </form>
  );
}

function DropSlot({ tag, file, onFile }) {
  const [over, setOver] = useState(false);
  const tone = tag.toLowerCase();

  function drop(event) {
    event.preventDefault();
    setOver(false);
    onFile(event.dataTransfer.files[0]);
  }

  return (
    <label
      className={["slot", over && "over", file && "filled"].filter(Boolean).join(" ")}
      onDragOver={(event) => {
        event.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={drop}
    >
      <span className={`letter tone-${tone}`}>{tag}</span>
      <span className="slot-text">
        <span className="slot-title">{file ? displayName(file.name) : `Policy ${tag}`}</span>
        <span className="slot-sub">{file ? formatSize(file.size) : "Drop a PDF here or browse"}</span>
      </span>
      {!file && (
        <span className="slot-icon">
          <Icon name="upload" />
        </span>
      )}
      <input type="file" accept="application/pdf,.pdf" onChange={(event) => onFile(event.target.files[0])} />
    </label>
  );
}
