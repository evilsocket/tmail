import { execFile } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { promisify } from 'node:util';

const execute = promisify(execFile);
export const addressPattern = /^[a-z0-9][a-z0-9._-]{0,63}@tmail\.internal$/;

export function privateRead(filename, limit = 65536) {
  const info = fs.lstatSync(filename);
  if (!info.isFile() || (info.mode & 0o077) || info.uid !== process.getuid() || info.size > limit) {
    throw new Error('Expected a private, owner-only regular file');
  }
  return fs.readFileSync(filename, 'utf8');
}

export function validateConfig(value) {
  const allowed = new Set(['host', 'port', 'username', 'passwordFile', 'passwordCommand', 'allowedSenders', 'stateDirectory']);
  if (!value || typeof value !== 'object' || Object.keys(value).some(key => !allowed.has(key))) {
    throw new Error('Unknown channel configuration field');
  }
  if (typeof value.host !== 'string' || !/^tmail(?:-[a-z0-9-]+)?\.[a-z0-9.-]+\.ts\.net$/.test(value.host)) {
    throw new Error('Expected the tmail ts.net TLS hostname');
  }
  if (!addressPattern.test(value.username) || /^(admin|owner|maintenance)@/.test(value.username)) {
    throw new Error('Expected a non-administrator agent mailbox');
  }
  const port = value.port ?? 993;
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('Invalid TLS port');
  if (typeof value.stateDirectory !== 'string' || !path.isAbsolute(value.stateDirectory)) {
    throw new Error('stateDirectory must be absolute');
  }
  if (Boolean(value.passwordFile) === Boolean(value.passwordCommand)) {
    throw new Error('Choose exactly one password source');
  }
  if (value.passwordFile && (typeof value.passwordFile !== 'string' || !path.isAbsolute(value.passwordFile))) {
    throw new Error('passwordFile must be absolute');
  }
  if (value.passwordCommand && (!Array.isArray(value.passwordCommand) || !value.passwordCommand.length ||
      value.passwordCommand.some(arg => typeof arg !== 'string') || !path.isAbsolute(value.passwordCommand[0]))) {
    throw new Error('passwordCommand must be an argv array with an absolute executable path');
  }
  if (!Array.isArray(value.allowedSenders) || value.allowedSenders.length > 100 ||
      value.allowedSenders.some(sender => typeof sender !== 'string' || !addressPattern.test(sender))) {
    throw new Error('allowedSenders must contain exact local email addresses');
  }
  return { ...value, port, allowedSenders: [...new Set(value.allowedSenders)] };
}

export async function passwordFor(config) {
  const password = (config.passwordFile ? privateRead(config.passwordFile) :
    (await execute(config.passwordCommand[0], config.passwordCommand.slice(1), {
      timeout: 10000, maxBuffer: 65536, encoding: 'utf8', shell: false,
    })).stdout).replace(/[\r\n]+$/, '');
  if (!password || /[\r\n\0]/.test(password)) throw new Error('Invalid password source output');
  return password;
}
