// Start the game on the clean image bundled with the page (pw64.data).
Module['arguments'] = Module['arguments'] || ['--clean', '/pilotwings64.clean.z64'];

// ---- WebAudio output (called from web_audio.cpp on the main thread)
Module.pw64AudioOpen = function () {
  if (!Module.pw64Audio) {
    var AC = window.AudioContext || window.webkitAudioContext;
    var ctx = new AC();
    var q = { ctx: ctx, chunks: [], head: 0, frames: 0 };
    var node = ctx.createScriptProcessor(2048, 0, 2);
    node.onaudioprocess = function (e) {
      var L = e.outputBuffer.getChannelData(0), R = e.outputBuffer.getChannelData(1);
      var i = 0;
      while (i < L.length && q.chunks.length) {
        var c = q.chunks[0];
        var n = Math.min(L.length - i, (c.length >> 1) - q.head);
        for (var k = 0; k < n; k++) {
          L[i + k] = c[(q.head + k) * 2] / 32768;
          R[i + k] = c[(q.head + k) * 2 + 1] / 32768;
        }
        i += n; q.head += n; q.frames -= n;
        if (q.head * 2 >= c.length) { q.chunks.shift(); q.head = 0; }
      }
      for (; i < L.length; i++) { L[i] = 0; R[i] = 0; }
    };
    node.connect(ctx.destination);
    var resume = function () { if (ctx.state !== 'running') ctx.resume(); };
    ['pointerdown', 'keydown', 'touchstart', 'gamepadconnected'].forEach(function (ev) {
      window.addEventListener(ev, resume, { passive: true });
    });
    Module.pw64Audio = q;
  }
  return Module.pw64Audio.ctx.sampleRate;
};
Module.pw64AudioQueue = function (ptr, bytes) {
  var q = Module.pw64Audio;
  if (!q) return;
  var n = bytes >> 1;
  var c = new Int16Array(n);
  c.set(HEAP16.subarray(ptr >> 1, (ptr >> 1) + n));
  q.chunks.push(c);
  q.frames += n >> 1;
  // A suspended context (no user gesture yet) must not grow the queue forever.
  while (q.frames > q.ctx.sampleRate && q.chunks.length > 1) {
    q.frames -= (q.chunks.shift().length >> 1) - q.head; q.head = 0;
  }
};
Module.pw64AudioFrames = function () { return Module.pw64Audio ? Module.pw64Audio.frames : 0; };
