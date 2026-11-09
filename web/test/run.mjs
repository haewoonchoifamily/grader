import assert from "node:assert/strict";
import * as CFB from "cfb";
import { zipSync, strToU8 } from "fflate";
import { deflateRawSync } from "node:zlib";
import { readHwp, readHwpx, parseParaText } from "../src/docs.js";
import { normChoice, normShort, gradeStudent } from "../src/grade.js";
import worker from "../src/worker.js";

// ---- 합성 HWP (OLE + raw deflate 압축 본문)
function rec(tag, payload) { const h = Buffer.alloc(4); h.writeUInt32LE((tag | (payload.length << 20)) >>> 0); return Buffer.concat([h, payload]); }
function para(text) {
  const ctrl = Buffer.concat([Buffer.from([2, 0]), Buffer.alloc(14)]); // 확장 컨트롤 16바이트
  return rec(67, Buffer.concat([ctrl, Buffer.from(text, "utf16le"), Buffer.from([13, 0])]));
}
const body = Buffer.concat([para("1. ③"), para("2. 서울"), para("3. 광합성")]);
const header = Buffer.alloc(256); header.writeUInt32LE(1, 36); // compressed
const cfb = CFB.utils.cfb_new();
CFB.utils.cfb_add(cfb, "/FileHeader", header);
CFB.utils.cfb_add(cfb, "/BodyText/Section0", deflateRawSync(body));
const hwp = new Uint8Array(CFB.write(cfb, { type: "array" }));
const t = await readHwp(hwp);
assert.equal(t, "1. ③\n2. 서울\n3. 광합성"); console.log("HWP 파서 OK");

// ---- HWPX
const sec = `<hs:sec xmlns:hs="a" xmlns:hp="b"><hp:p><hp:run><hp:t>1. ③</hp:t></hp:run></hp:p><hp:p><hp:run><hp:t>2. A &amp; B</hp:t></hp:run></hp:p></hs:sec>`;
const hx = zipSync({ "Contents/section0.xml": strToU8(sec) });
assert.equal(readHwpx(hx), "1. ③\n2. A & B"); console.log("HWPX 파서 OK");

// ---- 정규화
assert.equal(normChoice("④, ②"), "2,4"); assert.equal(normChoice("3번"), "3"); assert.equal(normShort("서 울!"), "서울"); console.log("정규화 OK");

// ---- Claude 모의 + 채점 + 워커 엔드포인트
const key = [
  { no: "1", type: "choice", answer: "3", points: 2, accepted: [], rubric: "" },
  { no: "2", type: "short", answer: "서울", points: 2, accepted: [], rubric: "" },
  { no: "3", type: "essay", answer: "빛에너지를 화학에너지로", points: 6, accepted: [], rubric: "각 3점" },
];
const calls = [];
globalThis.fetch = async (url, init) => {
  const body = JSON.parse(init.body); calls.push(body.system.slice(0, 10));
  let out;
  if (body.system.startsWith("당신은 시험 정답지")) out = { questions: key };
  else if (body.system.startsWith("당신은 학생 답안지")) out = { name: "이영희", student_id: "1", answers: { 1: { answer: "③", confidence: 0.9 }, 2: { answer: "Seoul", confidence: 0.5 }, 3: { answer: "빛으로 포도당 생성", confidence: 0.9 } } };
  else out = body.messages[0].content[0].text && JSON.parse(body.messages[0].content[0].text).items.map((i) => ({ no: i.no, earned: i.points / 2, comment: "일부" }));
  return new Response(JSON.stringify({ content: [{ type: "text", text: JSON.stringify(out) }] }), { status: 200 });
};
const env = { APP_PASSWORD: "pw", ANTHROPIC_API_KEY: "k" };
const call = (path, fields, pw = "pw", e = env) => {
  const fd = new FormData(); for (const [k, v] of Object.entries(fields)) fd.append(k, v);
  return worker.fetch(new Request("http://x" + path, { method: "POST", headers: { "x-app-password": pw }, body: fd }), e);
};
const file = new File([hx], "key.hwpx");
assert.equal((await call("/api/key", { file }, "bad")).status, 401);
assert.equal((await call("/api/key", { file }, "pw", {})).status, 503);          // 비밀번호 미설정 -> 거부
assert.equal((await call("/api/key", { file }, "")).status, 401);
const k = await (await call("/api/key", { file })).json(); assert.equal(k.questions.length, 3);
const r = await (await call("/api/student", { file: new File([hwp], "s1.hwp"), questions: JSON.stringify(k.questions) })).json();
assert.equal(r.total, 6); assert.equal(r.max_total, 10);
console.log(r.results.map((x) => `${x.no}:${x.status}:${x.earned}`).join(" "), r.warnings);
const bad = await call("/api/student", { file: new File([new Uint8Array(4)], "a.txt"), questions: "[]" });
assert.equal(bad.status, 500); console.log("워커/인증 OK");
