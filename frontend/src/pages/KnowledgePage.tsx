import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { api, apiFetch } from "../lib/api";

export function KnowledgePage() {
  const queryClient = useQueryClient();
  const { data: documents = [] } = useQuery({
    queryKey: ["documents"],
    queryFn: api.documents,
  });
  const [title, setTitle] = useState("");
  const [version, setVersion] = useState("1.0");
  const [file, setFile] = useState<File | null>(null);
  const [query, setQuery] = useState("退款多久到账？");
  const [results, setResults] = useState<Array<{ title: string; content: string; score: number }>>([]);

  const upload = useMutation({
    mutationFn: async () => {
      const form = new FormData();
      if (!file) throw new Error("请选择文件");
      form.append("file", file);
      form.append("title", title || file.name);
      form.append("version", version);
      return apiFetch("/knowledge/documents", { method: "POST", body: form });
    },
    onSuccess: async () => {
      setTitle("");
      setFile(null);
      await queryClient.invalidateQueries({ queryKey: ["documents"] });
    },
  });

  async function submit(event: FormEvent) {
    event.preventDefault();
    await upload.mutateAsync();
  }

  async function search() {
    const response = await apiFetch<{ results: typeof results }>("/knowledge/search-test", {
      method: "POST",
      body: JSON.stringify({ query, top_k: 4 }),
    });
    setResults(response.results);
  }

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <span className="eyebrow">RAG OPERATIONS</span>
          <h1>知识库管理</h1>
          <p>上传售后政策并执行混合检索测试。</p>
        </div>
      </header>
      <div className="knowledge-grid">
        <form className="upload-card" onSubmit={submit}>
          <h2>上传政策文档</h2>
          <label>
            标题
            <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="例如：退款政策 2026" />
          </label>
          <label>
            版本
            <input value={version} onChange={(event) => setVersion(event.target.value)} />
          </label>
          <label>
            文件
            <input
              type="file"
              accept=".pdf,.docx,.md,.txt"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            />
          </label>
          <button className="primary-button" disabled={upload.isPending}>
            {upload.isPending ? "上传中…" : "上传并索引"}
          </button>
          {upload.error && <div className="form-error">{upload.error.message}</div>}
        </form>

        <section className="search-card">
          <h2>检索测试</h2>
          <div className="search-row">
            <input value={query} onChange={(event) => setQuery(event.target.value)} />
            <button className="primary-button" onClick={search}>检索</button>
          </div>
          <div className="search-results">
            {results.map((result, index) => (
              <article key={`${result.title}-${index}`}>
                <strong>{result.title || `结果 ${index + 1}`}</strong>
                <span>score {result.score.toFixed(3)}</span>
                <p>{result.content}</p>
              </article>
            ))}
            {!results.length && <div className="empty-block">运行一次检索查看召回片段。</div>}
          </div>
        </section>
      </div>

      <section className="table-card">
        <h2>已上传文档</h2>
        <table>
          <thead>
            <tr><th>标题</th><th>版本</th><th>状态</th><th>切片数</th><th /></tr>
          </thead>
          <tbody>
            {documents.map((document) => (
              <tr key={document.id}>
                <td>{document.title}</td>
                <td>{document.version}</td>
                <td><span className="table-status">{document.status}</span></td>
                <td>{document.chunk_count}</td>
                <td>
                  <button
                    className="text-button danger"
                    onClick={async () => {
                      await api.deleteDocument(document.id);
                      await queryClient.invalidateQueries({ queryKey: ["documents"] });
                    }}
                  >
                    删除
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
