// Scan subprocesses may read local assets but must not bootstrap or contact a service.
import net from "node:net";
import tls from "node:tls";
import dns from "node:dns";
import childProcess from "node:child_process";
import { syncBuiltinESMExports } from "node:module";

const blocked = () => { throw new Error("Network and child processes are disabled during detection"); };
net.Socket.prototype.connect = blocked;
net.connect = net.createConnection = tls.connect = blocked;
dns.lookup = dns.resolve = blocked;
dns.promises.lookup = dns.promises.resolve = blocked;
globalThis.fetch = blocked;
for (const method of ["spawn", "spawnSync", "exec", "execSync", "execFile", "execFileSync", "fork"]) {
    childProcess[method] = blocked;
}
syncBuiltinESMExports();
