import { useCallback, useState } from "react";
import { api } from "../api.js";
import { useJobEvents } from "../useJobEvents.js";
import { DocsArt, Icon, Logo } from "./Icons.jsx";
import JobList from "./JobList.jsx";
import JobReport from "./JobReport.jsx";
import UploadForm from "./UploadForm.jsx";

export default function Dashboard({ user, onLogout }) {
  const [jobs, setJobs] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [error, setError] = useState("");

  const loadJobs = useCallback(async () => {
    try {
      const data = await api.listJobs();
      setJobs(data.jobs);
      setError("");
    } catch (err) {
      setError(err.message);
    }
  }, []);

  function updateStatus({ job_id, status }) {
    if (status === "queued") {
      loadJobs();
      return;
    }
    setJobs((current) => current.map((job) => (job.job_id === job_id ? { ...job, status } : job)));
  }

  useJobEvents(loadJobs, updateStatus);

  function jobCreated(jobId) {
    setSelectedId(jobId);
    loadJobs();
  }

  const selected = jobs.find((job) => job.job_id === selectedId);
  const initial = user?.email?.charAt(0).toUpperCase() ?? "";

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <Logo />
          <span>Wording Comparator</span>
        </div>
        <div className="account">
          <span className="avatar" aria-hidden="true">
            {initial}
          </span>
          <span className="email">{user?.email}</span>
          <button className="icon-button" onClick={onLogout} title="Log out" aria-label="Log out">
            <Icon name="logout" />
          </button>
        </div>
      </header>

      <div className="layout">
        <aside className="sidebar">
          <UploadForm onCreated={jobCreated} />
          {error && <p className="form-error">{error}</p>}
          <JobList jobs={jobs} selectedId={selectedId} onSelect={setSelectedId} />
        </aside>

        <main className="content">
          {selectedId ? (
            <JobReport key={selectedId} jobId={selectedId} status={selected?.status} />
          ) : (
            <Welcome hasJobs={jobs.length > 0} />
          )}
        </main>
      </div>
    </div>
  );
}

function Welcome({ hasJobs }) {
  return (
    <div className="sheet welcome">
      <DocsArt />
      <h1 className="display">{hasJobs ? "Pick a comparison" : "Compare two policy wordings"}</h1>
      <p className="muted">
        {hasJobs
          ? "Choose one from the list, or start a new comparison."
          : "Add two policy PDFs on the left. You will get a verdict for every subject, in about a minute."}
      </p>
      <ol className="steps">
        <li>
          <span>1</span>Choose policy A and policy B
        </li>
        <li>
          <span>2</span>We read both and find the common subjects
        </li>
        <li>
          <span>3</span>Each subject gets a verdict, a reason and page references
        </li>
      </ol>
    </div>
  );
}
