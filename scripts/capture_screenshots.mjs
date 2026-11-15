import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { execSync } from 'child_process';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUT_DIR = path.resolve(__dirname, '../docs/screenshots');
fs.mkdirSync(OUT_DIR, { recursive: true });

async function getWsUrl() {
  const res = await fetch('http://localhost:9222/json/new', { method: 'PUT' });
  const json = await res.json();
  return json.webSocketDebuggerUrl;
}

class CDPClient {
  constructor(wsUrl) {
    this.wsUrl = wsUrl;
    this.ws = new WebSocket(wsUrl);
    this.id = 1;
    this.callbacks = new Map();
  }

  async connect() {
    return new Promise((resolve, reject) => {
      this.ws.onopen = () => resolve();
      this.ws.onerror = (e) => reject(e);
      this.ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        if (msg.id && this.callbacks.has(msg.id)) {
          const { resolve, reject } = this.callbacks.get(msg.id);
          this.callbacks.delete(msg.id);
          if (msg.error) {
            reject(new Error(msg.error.message));
          } else {
            resolve(msg.result);
          }
        }
      };
    });
  }

  send(method, params = {}) {
    return new Promise((resolve, reject) => {
      const id = this.id++;
      this.callbacks.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }

  close() {
    this.ws.close();
  }
}

async function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function run() {
  console.log('Connecting to Chrome CDP...');
  const wsUrl = await getWsUrl();
  const cdp = new CDPClient(wsUrl);
  await cdp.connect();
  console.log('Connected to CDP.');

  await cdp.send('Page.enable');
  await cdp.send('DOM.enable');
  await cdp.send('Emulation.setDeviceMetricsOverride', {
    width: 1280,
    height: 800,
    deviceScaleFactor: 1,
    mobile: false,
  });

  const pages = [
    { name: 'dashboard', url: 'http://localhost:5173/', wait: 4000 },
    { name: 'player-profile', url: 'http://localhost:5173/players/5dbf3cbf-2274-4b20-8bad-896ec7a98f2d', wait: 4000 },
    { name: 'matchup', url: 'http://localhost:5173/matchups', wait: 4000 },
    { name: 'match-centre', url: 'http://localhost:5173/matches/ef6652fa-e117-46aa-991b-e4dd6a47c39a', wait: 5000 },
    { name: 'simulator', url: 'http://localhost:5173/simulator', wait: 4000 },
    { name: 'scouting', url: 'http://localhost:5173/scouting', wait: 4000 },
    { name: 'venue', url: 'http://localhost:5173/venues/c41150fe-dfc8-4e66-bba7-f5a5649b854b', wait: 4000 },
  ];

  const captured = [];

  for (const page of pages) {
    console.log(`Navigating to ${page.name} (${page.url})...`);
    await cdp.send('Page.navigate', { url: page.url });
    await sleep(page.wait);

    // capture viewport screenshot
    const res = await cdp.send('Page.captureScreenshot', {
      format: 'png',
    });

    const filePath = path.join(OUT_DIR, `${page.name}.png`);
    fs.writeFileSync(filePath, Buffer.from(res.data, 'base64'));
    const size = fs.statSync(filePath).size;
    console.log(`Saved ${page.name}.png (${Math.round(size / 1024)} KB)`);
    captured.push({ name: page.name, size });
  }

  // Now record frames for demo.gif
  console.log('Recording frames for demo.gif...');
  const framesDir = path.join(OUT_DIR, 'frames');
  fs.mkdirSync(framesDir, { recursive: true });

  let frameCount = 0;
  for (const page of pages) {
    await cdp.send('Page.navigate', { url: page.url });
    await sleep(2500);

    // Capture 5 frames per page (scrolling slightly)
    for (let f = 0; f < 5; f++) {
      if (f > 0) {
        await cdp.send('Runtime.evaluate', {
          expression: `window.scrollBy(0, 180);`,
        });
        await sleep(500);
      }
      const frameRes = await cdp.send('Page.captureScreenshot', {
        format: 'png',
      });
      const framePath = path.join(framesDir, `frame_${String(frameCount++).padStart(4, '0')}.png`);
      fs.writeFileSync(framePath, Buffer.from(frameRes.data, 'base64'));
    }
  }

  console.log(`Captured ${frameCount} frames. Generating GIF with ffmpeg...`);
  const gifPath = path.join(OUT_DIR, 'demo.gif');
  // 35 frames at ~1.2 fps = ~30s duration, scaled to 800px width with palettegen for high quality under 8MB
  const ffmpegCmd = `ffmpeg -y -framerate 1.2 -i "${framesDir}/frame_%04d.png" -vf "fps=10,scale=800:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=128[p];[s1][p]paletteuse=dither=bayer" "${gifPath}"`;
  execSync(ffmpegCmd);

  const gifSize = fs.statSync(gifPath).size;
  console.log(`Generated demo.gif: ${Math.round(gifSize / 1024)} KB`);

  // Cleanup frames
  fs.rmSync(framesDir, { recursive: true, force: true });

  cdp.close();
  console.log('Done!');
}

run().catch((err) => {
  console.error(err);
  process.exit(1);
});
