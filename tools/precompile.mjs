// Build-time JSX compile. Usage: node tools/precompile.mjs <in.js> <out.js>
// Classic runtime so the global React UMD is used (no imports are introduced).
import { readFileSync, writeFileSync } from 'node:fs';
import Babel from '@babel/standalone';

const [, , inPath, outPath] = process.argv;
if (!inPath || !outPath) { console.error('usage: precompile.mjs <in.js> <out.js>'); process.exit(2); }
const src = readFileSync(inPath, 'utf8');
const { code } = Babel.transform(src, {
  presets: [['react', { runtime: 'classic' }]],
  sourceType: 'script',
  retainLines: true,
  compact: false,
  comments: false,
});
if (code.includes('</script')) { console.error('compiled output contains </script'); process.exit(3); }
writeFileSync(outPath, code, 'utf8');
console.log(`precompiled ${src.length.toLocaleString()} -> ${code.length.toLocaleString()} chars`);
