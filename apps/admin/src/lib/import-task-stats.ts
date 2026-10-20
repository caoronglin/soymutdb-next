/** Status counts describe the current page; total describes the filtered result set. */
export function summarizeImportPage(
  tasks: ReadonlyArray<{ status: string }>,
  filteredTotal: number,
) {
  const counts = { total: filteredTotal, running: 0, failed: 0, completed: 0 };
  for (const task of tasks) {
    if (task.status === "running" || task.status === "queued") counts.running += 1;
    else if (task.status === "failed") counts.failed += 1;
    else if (task.status === "completed") counts.completed += 1;
  }
  return counts;
}
