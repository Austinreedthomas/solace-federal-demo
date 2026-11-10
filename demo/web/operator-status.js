(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.OperatorStatus = factory();
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  var INTERVAL_MS = 1000;
  var TIMEOUT_MS = 2500;

  function createPoller() {
    var actionSerial = 0;
    var flight = 0;
    var inFlight = false;
    var listenBusy = false;
    return {
      intervalMs: INTERVAL_MS,
      timeoutMs: TIMEOUT_MS,
      startRefresh: function () {
        if (inFlight || listenBusy) return null;
        inFlight = true;
        flight += 1;
        return { serial: actionSerial, id: flight };
      },
      finishRefresh: function (ticket, ok) {
        if (!ticket) return "ignore";
        if (ticket.id === flight) inFlight = false;
        if (ticket.serial !== actionSerial || listenBusy) return "ignore";
        return ok ? "apply" : "unverified";
      },
      beginListen: function () {
        listenBusy = true;
        actionSerial += 1;
        flight += 1;
        inFlight = false;
      },
      endListen: function () {
        listenBusy = false;
      },
      isListenBusy: function () {
        return listenBusy;
      }
    };
  }

  var UNVERIFIED = {
    headline: "Receiving status unavailable. This page could not verify the Solace receiver.",
    pill: "Not verified",
    note: "The endpoint and authentication note are the last ones received. They were not checked again.",
    queue: "Queue count unavailable. It was not checked again."
  };

  return {
    createPoller: createPoller,
    UNVERIFIED: UNVERIFIED,
    INTERVAL_MS: INTERVAL_MS,
    TIMEOUT_MS: TIMEOUT_MS
  };
});
