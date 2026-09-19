/** Start only on Node A. Use node --env-file=.env --experimental-strip-types. */
import {gatewayFromEnvironment, DEFAULT_PORT} from '../src/gemma-gateway.ts';
const server = gatewayFromEnvironment();
server.listen(DEFAULT_PORT,'127.0.0.1',()=>{
  console.log(`AXONVERTEX_GATEWAY_READY http://127.0.0.1:${DEFAULT_PORT}`);
});
for(const signal of ['SIGTERM','SIGINT']) process.on(signal,()=>server.close(()=>process.exit(0)));
