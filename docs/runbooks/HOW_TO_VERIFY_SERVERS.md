# How to verify the servers

You confirm the four apps with the checks below. Start the apps, and then check each health route. After the health checks, send one question through the search bar. The finished response includes a path. The path lists every app twice, once on the way to the database and once on the way back.

The ports and the job of each app are in [How the app servers work](HOW_THE_APP_SERVERS_WORK.md).

## Start the apps

Run each command from the repo root, in its own terminal. Start the database first. Then start the AI server, and then start the backend. Start the search bar last.

```bash
uv run python -m data_explorer_agents.database.app
uv run python -m data_explorer_agents.ai.app
uv run python -m data_explorer_agents.backend.app
uv run python -m data_explorer_agents.ui.app
```

## Check that each app is up

Run these requests. Each response names the app on that port.

```bash
curl -sf http://127.0.0.1:8000/health
curl -sf http://127.0.0.1:8001/health
curl -sf http://127.0.0.1:8002/health
curl -sf http://127.0.0.1:8003/health
```

The responses are `{"service":"ui"}`, `{"service":"backend"}`, `{"service":"ai"}`, and `{"service":"database"}`.

## Send a question through the search bar

Send a question that should match the galaxy catalog.

```bash
curl -sS -X POST http://127.0.0.1:8000/search \
  -H 'content-type: application/json' \
  -d '{"question":"Which datasets contain galaxies?"}'
```

The result names SDSS galaxies. The path is exactly `["ui","backend","ai","database","ai","backend","ui"]`.

## Check a question with no matching rows

Send a question that shares no words with the sample catalogs.

```bash
curl -sS -X POST http://127.0.0.1:8000/search \
  -H 'content-type: application/json' \
  -d '{"question":"Where are the volcanoes?"}'
```

The result says that no datasets matched. The `rows` list is empty. The path is the same full path as the galaxy question, so you can see that the question reached the database and came back.

## Check a blank question

Send a question that is only spaces.

```bash
curl -sS -o /dev/null -w '%{http_code}\n' -X POST http://127.0.0.1:8000/search \
  -H 'content-type: application/json' \
  -d '{"question":"   "}'
```

The status code is 422, because a blank question is rejected before any other app is called.

## Check the search page

Open `http://127.0.0.1:8000` in a browser. Type `Which datasets contain galaxies?` into the search box and click Search. The page shows the SDSS galaxies result, and the page shows the path `ui → backend → ai → database → ai → backend → ui`.
