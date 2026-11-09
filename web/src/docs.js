// HWP / HWPX 텍스트 추출 (Workers 호환: DecompressionStream, cfb, fflate)
import * as CFB from "cfb";
import { unzipSync, strFromU8 } from "fflate";

const toU8 = (c) => (c instanceof Uint8Array ? c : Uint8Array.from(c));

async function inflateRaw(u8) {
  const stream = new Blob([u8]).stream().pipeThrough(new DecompressionStream("deflate-raw"));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

const HWPTAG_PARA_TEXT = 0x10 + 51;
// 16바이트(문자 2 + 부가정보 14)를 차지하는 컨트롤 문자: 1~9(탭 포함), 11, 12, 14~23
const SKIP16 = new Set([1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23]);

export function parseParaText(u8) {
  const dv = new DataView(u8.buffer, u8.byteOffset, u8.byteLength);
  const out = [];
  let i = 0;
  const n = u8.byteLength;
  while (i + 1 < n) {
    const ch = dv.getUint16(i, true);
    if (ch >= 32) { out.push(String.fromCharCode(ch)); i += 2; }
    else if (ch === 10 || ch === 13) { out.push("\n"); i += 2; }
    else if (ch === 24) { out.push("-"); i += 2; }
    else if (ch === 30 || ch === 31) { out.push(" "); i += 2; }
    else if (ch === 9) { out.push("\t"); i += 16; }
    else if (SKIP16.has(ch)) { i += 16; }
    else i += 2;
  }
  return out.join("");
}

function* iterRecords(u8) {
  const dv = new DataView(u8.buffer, u8.byteOffset, u8.byteLength);
  let i = 0;
  const n = u8.byteLength;
  while (i + 4 <= n) {
    const header = dv.getUint32(i, true);
    i += 4;
    const tag = header & 0x3ff;
    let size = (header >>> 20) & 0xfff;
    if (size === 0xfff) {
      if (i + 4 > n) break;
      size = dv.getUint32(i, true);
      i += 4;
    }
    yield [tag, u8.subarray(i, i + size)];
    i += size;
  }
}

export async function readHwp(buf) {
  const u8 = buf instanceof Uint8Array ? buf : new Uint8Array(buf);
  // 확장자만 .hwp인 HWPX(zip) 대응
  if (u8[0] === 0x50 && u8[1] === 0x4b) return readHwpx(u8);
  const cfb = CFB.read(u8, { type: "array" });
  const header = CFB.find(cfb, "/FileHeader");
  if (!header) throw new Error("올바른 HWP 파일이 아닙니다.");
  const hdr = toU8(header.content);
  const flags = new DataView(hdr.buffer, hdr.byteOffset, hdr.byteLength).getUint32(36, true);
  if (flags & 2) throw new Error("암호가 걸린 HWP 파일입니다. 암호를 해제한 뒤 사용해 주세요.");
  const compressed = !!(flags & 1);

  const sections = cfb.FileIndex
    .map((e, i) => [e, cfb.FullPaths[i]])
    .filter(([e, p]) => /\/BodyText\/Section\d+$/.test(p))
    .map(([e]) => e)
    .sort((a, b) => parseInt(a.name.slice(7)) - parseInt(b.name.slice(7)));
  const paras = [];
  for (const sec of sections) {
    let raw = toU8(sec.content);
    if (compressed) raw = await inflateRaw(raw);
    for (const [tag, payload] of iterRecords(raw)) {
      if (tag === HWPTAG_PARA_TEXT) {
        const s = parseParaText(payload).trim();
        if (s) paras.push(s);
      }
    }
  }
  return paras.join("\n");
}

const ENT = { "&lt;": "<", "&gt;": ">", "&amp;": "&", "&quot;": '"', "&apos;": "'" };
function decodeEntities(s) {
  return s
    .replace(/&(lt|gt|amp|quot|apos);/g, (m) => ENT[m])
    .replace(/&#x([0-9a-f]+);/gi, (_, h) => String.fromCodePoint(parseInt(h, 16)))
    .replace(/&#(\d+);/g, (_, d) => String.fromCodePoint(parseInt(d, 10)));
}

export function readHwpx(buf) {
  const files = unzipSync(buf instanceof Uint8Array ? buf : new Uint8Array(buf));
  const names = Object.keys(files)
    .filter((n) => /^Contents\/section\d+\.xml$/.test(n))
    .sort((a, b) => parseInt(a.match(/\d+/)[0]) - parseInt(b.match(/\d+/)[0]));
  const lines = [];
  for (const name of names) {
    const xml = strFromU8(files[name]);
    let cur = "";
    const re = /<(?:\w+:)?t(?:\s[^>]*)?>([\s\S]*?)<\/(?:\w+:)?t>|<\/(?:\w+:)?p>|<(?:\w+:)?lineBreak\s*\/>/g;
    let m;
    while ((m = re.exec(xml))) {
      if (m[1] !== undefined) {
        cur += decodeEntities(m[1].replace(/<(?:\w+:)?tab\s*\/>/g, "\t").replace(/<[^>]+>/g, ""));
      } else {
        const t = cur.trim();
        if (t) lines.push(t);
        cur = "";
      }
    }
    if (cur.trim()) lines.push(cur.trim());
  }
  // 표 안/밖 중복으로 생기는 연속 중복 줄 제거
  return lines.filter((l, i) => l !== lines[i - 1]).join("\n");
}
