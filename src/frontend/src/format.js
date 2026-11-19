// Small display helpers shared by the components.

export function displayName(filename = "") {
  return filename.replace(/\.pdf$/i, "");
}

export function plural(count, word) {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}

export function subjectTitle(key) {
  const words = key.replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function formatSize(bytes) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatDate(seconds) {
  return new Date(Number(seconds) * 1000).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

// "Just now", "5 min ago", "3 h ago", then the date.
export function relativeTime(seconds) {
  const minutes = Math.floor((Date.now() / 1000 - Number(seconds)) / 60);
  if (minutes < 1) return "Just now";
  if (minutes < 60) return `${minutes} min ago`;
  if (minutes < 24 * 60) return `${Math.floor(minutes / 60)} h ago`;
  return new Date(Number(seconds) * 1000).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}
