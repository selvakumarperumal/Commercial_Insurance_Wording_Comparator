import { useEffect, useState } from "react";
import { api } from "../api.js";
import { displayName, formatDate, plural, relativeTime, subjectTitle } from "../format.js";
import { Icon } from "./Icons.jsx";
import StatusBadge from "./StatusBadge.jsx";

// In bar order: A's side, the middle, B's side.
const VERDICTS = [
  { key: "A_more_favourable", label: "A more favourable", tone: "a" },
  { key: "only_in_A", label: "Only in A", tone: "a-light" },
  { key: "equivalent", label: "Equivalent", tone: "same" },
  { key: "only_in_B", label: "Only in B", tone: "b-light" },
  { key: "B_more_favourable", label: "B more favourable", tone: "b" },
];
const VERDICT_BY_KEY = Object.fromEntries(VERDICTS.map((verdict) => [verdict.key, verdict]));

const WAITING = {
  queued: ["Waiting for a free worker…", "The comparison starts as soon as a worker picks it up."],
  processing: ["Comparing the two wordings…", "Reading both policies and judging each subject."],
  retrying: ["Retrying after a temporary problem…", "This happens now and then; nothing to do on your side."],
};

function downloadMarkdown(job) {
  const url = URL.createObjectURL(new Blob([job.result_md], { type: "text/markdown" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `comparison-${job.job_id}.md`;
  link.click();
  URL.revokeObjectURL(url);
}

// `status` comes from the live job list, so the report reloads when the job finishes.
export default function JobReport({ jobId, status }) {
  const [job, setJob] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    api
      .getJob(jobId)
      .then((data) => !cancelled && setJob(data))
      .catch((err) => !cancelled && setError(err.message));
    return () => {
      cancelled = true;
    };
  }, [jobId, status]);

  if (error) return <Notice title="Could not load this comparison">{error}</Notice>;
  if (!job) return <div className="sheet skeleton-sheet" aria-busy="true" />;

  const result = job.result;

  return (
    <article className="sheet report">
      <div className="report-bar">
        <span className="eyebrow">Comparison · {formatDate(job.created_at)}</span>
        <div className="report-actions">
          <StatusBadge status={job.status} />
          {job.result_md && (
            <button className="secondary" onClick={() => downloadMarkdown(job)}>
              <Icon name="download" size={16} />
              Report
            </button>
          )}
        </div>
      </div>

      <header className="versus">
        <PolicySide tag="A" name={result?.policy_a.name} file={job.pdf_a_name} pages={result?.policy_a.pages} />
        <span className="vs-mark" aria-hidden="true">
          vs
        </span>
        <PolicySide tag="B" name={result?.policy_b.name} file={job.pdf_b_name} pages={result?.policy_b.pages} />
      </header>

      {job.status === "failed" && (
        <Notice title="This comparison could not be completed">{job.error || "Unknown error."}</Notice>
      )}
      {WAITING[job.status] && <Waiting status={job.status} since={job.created_at} />}
      {result && <Result result={result} />}
    </article>
  );
}

function PolicySide({ tag, name, file, pages }) {
  const tone = tag.toLowerCase();
  return (
    <div className={`policy-side side-${tone}`}>
      <span className={`letter tone-${tone}`}>{tag}</span>
      <div>
        <h2 className="display">{name || displayName(file)}</h2>
        <p className="muted small">
          {file}
          {pages ? ` · ${plural(pages, "page")}` : ""}
        </p>
      </div>
    </div>
  );
}

function Waiting({ status, since }) {
  const [title, text] = WAITING[status];
  return (
    <div className="waiting">
      <div className="progress" aria-hidden="true">
        <span />
      </div>
      <h3 className="display">{title}</h3>
      <p className="muted">
        {text} Started {relativeTime(since).toLowerCase()}; this usually takes a minute or two and the page updates
        by itself.
      </p>
      <div className="skeletons" aria-hidden="true">
        <span />
        <span />
        <span />
      </div>
    </div>
  );
}

function Notice({ title, children }) {
  return (
    <div className="notice" role="alert">
      <Icon name="alert" size={20} />
      <div>
        <strong>{title}</strong>
        <p>{children}</p>
      </div>
    </div>
  );
}

function headline(summary, total) {
  const a = (summary.A_more_favourable ?? 0) + (summary.only_in_A ?? 0);
  const b = (summary.B_more_favourable ?? 0) + (summary.only_in_B ?? 0);
  if (a > b) return { tone: "a", text: `Policy A comes out ahead on ${a} of ${plural(total, "subject")}.` };
  if (b > a) return { tone: "b", text: `Policy B comes out ahead on ${b} of ${plural(total, "subject")}.` };
  return { tone: "same", text: `The two policies are evenly matched across ${plural(total, "subject")}.` };
}

function Result({ result }) {
  const [filter, setFilter] = useState("all");
  const total = result.comparisons.length;
  const summary = result.summary;
  const lead = headline(summary, total);
  const rows = filter === "all" ? result.comparisons : result.comparisons.filter((row) => row.verdict === filter);

  return (
    <>
      <section className="balance">
        <p className={`balance-headline display lead-${lead.tone}`}>{lead.text}</p>
        <div className="bar" role="img" aria-label="Verdicts per subject">
          {VERDICTS.filter((verdict) => summary[verdict.key]).map((verdict) => (
            <span
              key={verdict.key}
              className={`seg tone-${verdict.tone}`}
              style={{ flexGrow: summary[verdict.key] }}
              title={`${verdict.label}: ${summary[verdict.key]}`}
            />
          ))}
        </div>
        <ul className="legend">
          {VERDICTS.map((verdict) => (
            <li key={verdict.key} className={summary[verdict.key] ? "" : "zero"}>
              <span className={`swatch tone-${verdict.tone}`} />
              {verdict.label}
              <strong>{summary[verdict.key] ?? 0}</strong>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <div className="subjects-head">
          <h3 className="display">Subject by subject</h3>
          <div className="filters" role="group" aria-label="Filter subjects by verdict">
            <button aria-pressed={filter === "all"} onClick={() => setFilter("all")}>
              All <span>{total}</span>
            </button>
            {VERDICTS.filter((verdict) => summary[verdict.key]).map((verdict) => (
              <button
                key={verdict.key}
                aria-pressed={filter === verdict.key}
                onClick={() => setFilter(verdict.key)}
              >
                {verdict.label} <span>{summary[verdict.key]}</span>
              </button>
            ))}
          </div>
        </div>

        <ol className="subjects">
          {rows.map((row) => (
            <Subject key={row.subject} row={row} />
          ))}
        </ol>
      </section>
    </>
  );
}

function Subject({ row }) {
  const verdict = VERDICT_BY_KEY[row.verdict] ?? { label: row.verdict, tone: "same" };
  return (
    <li className={`subject edge-${verdict.tone}`}>
      <div className="subject-head">
        <div>
          <h4>{subjectTitle(row.subject)}</h4>
          <p className="muted small">{row.description}</p>
        </div>
        <span className={`verdict tone-${verdict.tone}`}>{verdict.label}</span>
      </div>
      <p className="reason">{row.reason}</p>
      <div className="sources">
        <Source tag="A" locations={row.policy_a_passages} />
        <Source tag="B" locations={row.policy_b_passages} />
      </div>
    </li>
  );
}

function Source({ tag, locations }) {
  return (
    <span className="source">
      <span className={`mini-letter tone-${tag.toLowerCase()}`}>{tag}</span>
      {locations.length ? locations.join(", ") : "not found"}
    </span>
  );
}
