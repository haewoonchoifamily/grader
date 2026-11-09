import { readHwp, readHwpx } from "./docs.js";
import { fileBlocks, parseKey, extractStudent, gradeStudent } from "./grade.js";

const MAX_BYTES = 25 * 1024 * 1024;
const json = (obj, status = 200) =>
  new Response(JSON.stringify(obj), { status, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" } });

function safeEqual(a, b) {
  const ea = new TextEncoder().encode(a), eb = new TextEncoder().encode(b);
  let diff = ea.length ^ eb.length;
  for (let i = 0; i < Math.max(ea.length, eb.length); i++) diff |= (ea[i] ?? 0) ^ (eb[i] ?? 0);
  return diff === 0;
}

async function loadFile(file) {
  if (!file || typeof file === "string") throw new Error("파일이 없습니다.");
  if (file.size > MAX_BYTES) throw new Error("파일이 너무 큽니다 (최대 25MB).");
  const name = file.name || "file";
  const ext = name.split(".").pop().toLowerCase();
  const data = new Uint8Array(await file.arrayBuffer());
  if (ext === "hwp") return { name, parts: { text: await readHwp(data) } };
  if (ext === "hwpx") return { name, parts: { text: readHwpx(data) } };
  if (ext === "pdf") return { name, parts: { pdf: data } };
  if (["jpg", "jpeg", "png", "gif", "webp"].includes(ext)) {
    const type = ext === "jpg" ? "image/jpeg" : `image/${ext}`;
    return { name, parts: { image: { type, data } } };
  }
  throw new Error(`지원하지 않는 형식입니다: .${ext} (hwp, hwpx, pdf, jpg, png, gif, webp)`);
}

async function handle(request, env) {
  const url = new URL(request.url);
  if (request.method !== "POST") return json({ error: "POST만 지원합니다." }, 405);

  // 인증: APP_PASSWORD가 설정되지 않았으면 모든 요청 거부 (fail closed)
  if (!env.APP_PASSWORD || !env.ANTHROPIC_API_KEY) return json({ error: "서버 설정이 완료되지 않았습니다 (APP_PASSWORD, ANTHROPIC_API_KEY)." }, 503);
  if (!safeEqual(request.headers.get("x-app-password") ?? "", env.APP_PASSWORD)) return json({ error: "비밀번호가 올바르지 않습니다." }, 401);

  const form = await request.formData();
  const { name, parts } = await loadFile(form.get("file"));

  if (url.pathname === "/api/key") {
    const questions = await parseKey(env, fileBlocks("정답지", name, parts));
    return json({ questions });
  }
  if (url.pathname === "/api/student") {
    const questions = JSON.parse(form.get("questions") || "[]");
    if (!Array.isArray(questions) || !questions.length) return json({ error: "정답지 정보가 없습니다." }, 400);
    const stu = await extractStudent(env, fileBlocks("학생 시험지", name, parts), questions);
    return json(await gradeStudent(env, questions, stu, name));
  }
  return json({ error: "not found" }, 404);
}

export default {
  async fetch(request, env) {
    try {
      return await handle(request, env);
    } catch (e) {
      return json({ error: String(e.message ?? e) }, 500);
    }
  },
};
