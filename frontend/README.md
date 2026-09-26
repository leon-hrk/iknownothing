# Frontend

React single-page application: course tree, chat, and Markdown reader
(see [arc42 chapter 1, User Interface](../docs/arc42/01-introduction-and-goals.adoc)).

```sh
cd frontend
npm install
npm run dev      # on :5173, proxies /api to the backend on :8000
npm run build    # into dist/
```

The backend serves `dist/` when `IKN_FRONTEND_DIR` points to it.
