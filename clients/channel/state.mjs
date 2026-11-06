import fs from 'node:fs';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import lockfile from 'proper-lockfile';
import { addressPattern, privateRead } from './config.mjs';

export const MAX_PENDING = 100;
const uid = value => Number.isInteger(value) && value >= 0 && value <= 4294967295;

export class State {
  static async open(config) {
    fs.mkdirSync(config.stateDirectory, { recursive: true, mode: 0o700 });
    const info = fs.lstatSync(config.stateDirectory);
    if (!info.isDirectory() || (info.mode & 0o077) || info.uid !== process.getuid()) {
      throw new Error('State directory must be private and owned by this user');
    }
    const release = await lockfile.lock(config.stateDirectory, { stale: 10000, update: 2000, retries: 0 });
    try {
      return new State(config, release);
    } catch (error) {
      await release();
      throw error;
    }
  }

  constructor(config, release) {
    this.filename = path.join(config.stateDirectory, 'state.json');
    this.identity = `${config.host}:${config.port}/${config.username}/INBOX`;
    this.release = release;
    this.data = null;
    try {
      const data = JSON.parse(privateRead(this.filename));
      if (data.version !== 1 || data.identity !== this.identity || !/^[1-9][0-9]*$/.test(data.uidValidity) ||
          !uid(data.cursor) || !Array.isArray(data.pending) || data.pending.length > MAX_PENDING ||
          data.pending.some(event => !uid(event.uid) || event.uid < 1 || event.uid > data.cursor ||
            event.id !== `${data.uidValidity}:${event.uid}` || !addressPattern.test(event.sender)) ||
          new Set(data.pending.map(event => event.id)).size !== data.pending.length) {
        throw new Error('Invalid channel state; preserve it for recovery');
      }
      this.data = data;
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
    }
  }

  save() {
    const temporary = `${this.filename}.${randomUUID()}.tmp`;
    let descriptor;
    try {
      descriptor = fs.openSync(temporary, 'wx', 0o600);
      fs.writeFileSync(descriptor, JSON.stringify(this.data) + '\n');
      fs.fsyncSync(descriptor);
      fs.closeSync(descriptor);
      descriptor = undefined;
      fs.renameSync(temporary, this.filename);
      const directory = fs.openSync(path.dirname(this.filename), 'r');
      try { fs.fsyncSync(directory); } finally { fs.closeSync(directory); }
    } finally {
      if (descriptor !== undefined) fs.closeSync(descriptor);
      fs.rmSync(temporary, { force: true });
    }
  }
}
