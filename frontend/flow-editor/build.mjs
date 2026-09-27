import {build} from 'esbuild';
import {mkdir, readFile, writeFile, readdir} from 'node:fs/promises';
import path from 'node:path';
const out = '../../flowops/streamlit/flow_editor_assets';
await mkdir(out, {recursive:true});
const result = await build({entryPoints:['src/editor.jsx'], bundle:true, minify:true, sourcemap:false, metafile:true, outfile:`${out}/editor.js`, define:{'process.env.NODE_ENV':'"production"'}, legalComments:'external'});
// Preserve complete copyright and license notices for every bundled package.
const packages = new Set(Object.keys(result.metafile.inputs).flatMap(input => {
  const match = input.replaceAll('\\', '/').match(/^(.*node_modules\/(?:@[^/]+\/)?[^/]+)\//);
  return match ? [match[1]] : [];
}));
const notices = [];
for (const directory of [...packages].sort()) {
  const metadata = JSON.parse(await readFile(path.join(directory, 'package.json'), 'utf8'));
  const licenses = (await readdir(directory)).filter(name => /^(license|licence|copying|notice)(\.|$)/i.test(name));
  if (!licenses.length) throw new Error(`Missing license for ${metadata.name}`);
  const texts = await Promise.all(licenses.sort().map(name => readFile(path.join(directory, name), 'utf8')));
  notices.push(`${metadata.name} ${metadata.version}\n${texts.join('\n')}`);
}
await writeFile(`${out}/THIRD_PARTY_NOTICES.txt`, notices.join('\n\n--------------------\n\n'));
await writeFile(`${out}/index.html`, '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="editor.css"></head><body><div id="root"></div><script src="editor.js"></script></body></html>');
