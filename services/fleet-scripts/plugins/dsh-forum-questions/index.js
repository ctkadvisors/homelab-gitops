// A dsh user-questions provider that asks on the fleet's forum (harness change
// 3 of 5, 2026-09-09). Inside a stage there is no human at a keyboard: the
// model's ask_user_question becomes a forum post mentioning chris and the
// concierge, the stage keeps waiting for a reply on that thread (reconcile's
// ask_concierge answers what it can; Chris answers the rest from Telegram),
// and the answer flows back into the tool result. No answer within the
// timeout: the model gets told so and continues under a stated assumption,
// instead of the run dying and being relaunched tomorrow.
//
// Plain ESM, no imports: cordis injects `userQuestions` (the service the
// dsh-base profile already mounts). Configure through the dsh patch:
//   - id: forum-questions
//     name: '@homelab/dsh-forum-questions'
//     config: { forumUrl, author, timeoutMs, pollMs }

export const name = "forum-questions";
export const inject = ["userQuestions"];

const DEFAULTS = {
  forumUrl: process.env.FORUM_URL || "http://fleet-console.kagent-system.svc:8081",
  author: process.env.FORUM_AUTHOR || "implementer",
  ref: process.env.FORUM_REF || undefined,
  timeoutMs: Number(process.env.FORUM_ASK_TIMEOUT_MS || 20 * 60 * 1000),
  pollMs: Number(process.env.FORUM_ASK_POLL_MS || 30 * 1000),
};

function render(questions) {
  return questions
    .map((q) => {
      const opts = (q.options || []).map((o) => `  - ${o.label}${o.description ? `: ${o.description}` : ""}`).join("\n");
      return `${q.header ? `[${q.header}] ` : ""}${q.question}${opts ? `\n${opts}` : ""}`;
    })
    .join("\n\n");
}

async function post(cfg, body) {
  const res = await fetch(`${cfg.forumUrl}/api/post`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`forum post failed: HTTP ${res.status}`);
  return (await res.json()).id;
}

async function replyTo(cfg, postId) {
  const res = await fetch(`${cfg.forumUrl}/api/forum?limit=80`);
  if (!res.ok) return undefined;
  const posts = (await res.json()).posts || [];
  return posts.find((p) => p.parent_id === postId && p.author !== cfg.author);
}

const sleep = (ms, signal) =>
  new Promise((resolve, reject) => {
    const t = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => { clearTimeout(t); reject(new Error("aborted")); }, { once: true });
  });

export function apply(ctx, config = {}) {
  const cfg = { ...DEFAULTS, ...config };
  const dispose = ctx.userQuestions.registerProvider({
    async ask(request) {
      const questions = request.questions || [];
      const text = render(questions);
      const id = await post(cfg, {
        author: cfg.author,
        topic: "question",
        body: `A running stage needs an answer to continue (reply on this thread):\n\n${text}`,
        ref: cfg.ref,
        mentions: ["chris", "concierge"],
      });
      const deadline = Date.now() + cfg.timeoutMs;
      let answer;
      while (Date.now() < deadline) {
        await sleep(cfg.pollMs, request.signal);
        answer = await replyTo(cfg, id).catch(() => undefined);
        if (answer) break;
      }
      const custom = answer
        ? String(answer.body)
        : `No answer arrived on the forum within ${Math.round(cfg.timeoutMs / 60000)} minutes (post ${id}). Decide yourself, say in your report exactly what you assumed, and finish.`;
      return { answers: questions.map((q) => ({ id: q.id, selected: [], custom })) };
    },
  });
  return dispose;
}
