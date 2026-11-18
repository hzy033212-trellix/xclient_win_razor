// Preloaded into hxsim (node --require, see hxsim_ioc.start_hxsim): turn off Node's
// per-request time limits, as a real HX server has none. Node >= 18 answers a
// request whose body isn't complete after requestTimeout (300 s) with 408; the
// daemon streams a large audit result (e.g. a 190 MB eventlogs audit) in one PUT
// as the audit produces it, for longer than that, and fails the task (-4071).
'use strict';

['http', 'https'].forEach(function (name) {
  var mod = require(name);
  var create = mod.createServer;
  mod.createServer = function () {
    var server = create.apply(this, arguments);
    server.requestTimeout = 0;
    server.headersTimeout = 0;
    server.timeout = 0;
    return server;
  };
});
