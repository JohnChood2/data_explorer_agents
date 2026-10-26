const form = document.getElementById("search-form");
const output = document.getElementById("output");

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const question = document.getElementById("question").value;
  output.textContent = "Searching…";
  try {
    const response = await fetch("/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    const body = await response.json();
    if (!response.ok) {
      output.textContent =
        typeof body.detail === "string" ? body.detail : JSON.stringify(body, null, 2);
      return;
    }
    const rows = (body.rows || [])
      .map((row) => `• ${row.name} (${row.row_count} rows)`)
      .join("\n");
    output.textContent = `${body.result}\n\n${rows}\n\npath: ${body.path.join(" → ")}`;
  } catch (error) {
    output.textContent = error instanceof Error ? error.message : String(error);
  }
});
