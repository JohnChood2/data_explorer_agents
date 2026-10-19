# How the app servers work

The search bar, the backend, the AI server, and the database are separate web apps. You start each app in its own process. You send a question from the search bar to the backend. The backend sends the question to the AI server, and the AI server sends the question to the database. The result comes back along the same path.

## Ports

| App | Port |
| --- | --- |
| Search bar | 8000 |
| Backend | 8001 |
| AI server | 8002 |
| Database | 8003 |

Each app is available only on 127.0.0.1, so only a program on your computer can call it. You can change a port, or the address of the next app, with an environment variable before you start that app.

- `UI_PORT` sets the search bar port, and `BACKEND_URL` sets the backend address the search bar calls. The default backend address is `http://127.0.0.1:8001`.
- `BACKEND_PORT` sets the backend port, and `AI_URL` sets the AI server address. The default AI server address is `http://127.0.0.1:8002`.
- `AI_PORT` sets the AI server port, and `DATABASE_URL` sets the database address. The default database address is `http://127.0.0.1:8003`.
- `DATABASE_PORT` sets the database port.

To check that the apps are running, and that a question passes through all four, follow [How to verify the servers](HOW_TO_VERIFY_SERVERS.md).

## What each app does

The search bar is the page at `http://127.0.0.1:8000`. You type a question and submit it. The page sends the question to `POST /search` on the search bar, and the search bar sends the question to `POST /search` on the backend.

The backend is the app on port 8001. `POST /search` on the backend sends the question to `POST /ask` on the AI server. The backend returns the AI server's result without changing the result text.

The AI server is the app on port 8002. `POST /ask` runs the data explorer graph. The graph calls the database MCP tool named `query`. That tool returns the matching rows, and the AI server writes one result sentence from those rows. The AI server does not call a language model.

The database is the app on port 8003. It keeps three sample datasets in memory, and it exposes them through `POST /query` and through an MCP server at `/mcp`. The MCP tool is named `query`, and it returns the same rows as `POST /query`.

- SDSS galaxies is a galaxy catalog with 120,000 rows.
- Gaia stars is a catalog of stellar positions with 1,800,000,000 rows.
- Kepler exoplanets is a catalog of confirmed exoplanets with 2,662 rows.

The database splits the question into words of at least four letters, and it ignores common words such as "which", "datasets", and "contain". A remaining word matches a row when one word starts with the first five letters of the other, using the row name and the row description. If every word is a common word, the database returns all three rows. If no word matches, the database returns no rows.

## How a question travels

The response includes a `path` list. The search bar appends `ui` before calling the backend. The backend appends `backend` before calling the AI server. The AI server appends `ai` before calling the database. The database appends `database` and returns the matching rows. The AI server, the backend, and the search bar each append their own name again while sending the result back. A complete path is `ui`, `backend`, `ai`, `database`, `ai`, `backend`, `ui`.

## How to start the apps

Run each command from the repo root, in its own terminal. Start the database first. Then start the AI server, and then start the backend. Start the search bar last, so each app can reach the app it calls.

```bash
uv run python -m data_explorer_agents.database.app
uv run python -m data_explorer_agents.ai.app
uv run python -m data_explorer_agents.backend.app
uv run python -m data_explorer_agents.ui.app
```
