// Mobile chat client for Jarvis: talks to the SAME backend (same conversation, same tools, same
// approval flow) as the voice loop on the Mac, over a plain HTTP POST. Voice input uses the browser's
// own speech recognition (nothing is routed through the Mac's Whisper) - note this only works in a
// "secure context" (https:, or http://localhost): a plain http://<lan-ip> page, which is what this is
// when opened from a phone, will likely have it blocked by the browser. Text input always works.

const log = document.getElementById("log");
const form = document.getElementById("bar");
const input = document.getElementById("text");
const micBtn = document.getElementById("mic");

function addMsg(text, who, pending) {
  const el = document.createElement("div");
  el.className = `msg ${who}` + (pending ? " pending" : "");
  el.textContent = text;
  log.appendChild(el);
  log.scrollTop = log.scrollHeight;
  return el;
}

async function send(text) {
  text = text.trim();
  if (!text) return;
  addMsg(text, "user");
  input.value = "";
  const placeholder = addMsg("...", "bot", true);
  try {
    const r = await fetch("/api/message", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    const data = await r.json();
    placeholder.remove();
    const reply = data.reply || data.error || "(no reply)";
    addMsg(reply, "bot");
    speak(reply);
  } catch (err) {
    placeholder.remove();
    addMsg("Couldn't reach Jarvis - check you're on the same Wi-Fi as the Mac.", "bot");
  }
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  send(input.value);
});

function speak(text) {
  try {
    if (!("speechSynthesis" in window)) return;
    const u = new SpeechSynthesisUtterance(text);
    speechSynthesis.speak(u);
  } catch (err) {
    // speech synthesis not available: the reply is still shown as text, nothing lost
  }
}

// ---- optional voice input (browser's own recognition, not the Mac's Whisper) ----
const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
if (!Recognition) {
  micBtn.remove();
} else {
  const rec = new Recognition();
  rec.lang = "en-US";
  rec.interimResults = false;
  let listening = false;

  micBtn.addEventListener("click", () => {
    if (listening) { rec.stop(); return; }
    try {
      rec.start();
      listening = true;
      micBtn.classList.add("listening");
    } catch (err) {
      addMsg("Voice input needs a secure page (https) - this plain http page can't use the microphone. Type instead.", "bot");
    }
  });
  rec.onresult = (e) => {
    const heard = e.results[0][0].transcript;
    input.value = heard;
    send(heard);
  };
  rec.onerror = (e) => {
    if (e.error === "not-allowed" || e.error === "service-not-allowed") {
      addMsg("Microphone access was blocked - on a plain http page (not https/localhost), Chrome often disables this. Type instead.", "bot");
    }
  };
  rec.onend = () => { listening = false; micBtn.classList.remove("listening"); };
}

addMsg("Connected. Ask me anything, or tap the mic if it's available on your phone.", "bot");
