// 音声入力。data-voice を付けた欄の下に「音声で入力」のボタンを置く。
// 話した言葉は、ブラウザーの音声認識（Web Speech API）で文字にして、欄の後ろに足す。
// 音声はブラウザーの中で扱い、このアプリのサーバーには送らない（文字にした結果だけを、フォームで送る）。
// 音声認識は、https か localhost のページでしか使えない。使えないブラウザーでは、ボタンを出さない。
(() => {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Recognition || !window.isSecureContext) return;

  let active = null; // 今、聞き取っている { recognition, button }

  const stop = () => {
    if (active) active.recognition.stop();
  };

  document.querySelectorAll("textarea[data-voice]").forEach((textarea) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "voice-button secondary outline";
    button.textContent = "音声で入力";
    const status = document.createElement("small");
    status.className = "voice-status";
    status.setAttribute("aria-live", "polite");
    textarea.after(button, status);

    button.addEventListener("click", () => {
      // もう一度押したら止める。別の欄を押したら、前の欄を止めてから始める
      if (active && active.button === button) {
        stop();
        return;
      }
      stop();
      const recognition = new Recognition();
      recognition.lang = "ja-JP";
      recognition.interimResults = false;
      recognition.continuous = true;
      recognition.addEventListener("result", (event) => {
        for (let i = event.resultIndex; i < event.results.length; i += 1) {
          if (event.results[i].isFinal) {
            textarea.value += event.results[i][0].transcript;
            textarea.dispatchEvent(new Event("input", { bubbles: true }));
          }
        }
      });
      recognition.addEventListener("error", (event) => {
        status.textContent =
          event.error === "not-allowed" || event.error === "service-not-allowed"
            ? "マイクを使えません。ブラウザーで、マイクを許可してください。"
            : "聞き取れませんでした。もう一度押してください。";
      });
      recognition.addEventListener("end", () => {
        button.textContent = "音声で入力";
        button.removeAttribute("aria-pressed");
        if (active && active.button === button) active = null;
      });
      active = { recognition, button };
      status.textContent = "話してください。終わったら、もう一度押します。";
      button.textContent = "止める";
      button.setAttribute("aria-pressed", "true");
      recognition.start();
    });
  });

  // 送信するときは、聞き取りを止める
  document.addEventListener("submit", stop);
})();
