// 質問の画面で、質問を1問ずつ出す。
// 3つの答えは、今までどおり1つのフォームでまとめて送る（サーバーの処理は変えない）。
// このファイルが動かないときは、3問が並んで出る。
(() => {
  const form = document.querySelector("form[data-stepper]");
  if (!form) return;
  const steps = Array.from(form.querySelectorAll("[data-step]"));
  if (steps.length < 2) return;
  const submit = form.querySelector('button[type="submit"]');
  const answerOf = (step) => step.querySelector("textarea");

  // 選択肢を見せる（JavaScript が動かないときは、隠したまま）
  form.querySelectorAll(".choice-chips").forEach((chips) => {
    chips.hidden = false;
  });
  form.querySelectorAll(".question-progress").forEach((p) => {
    p.hidden = false;
  });

  // 最後に、3つの答えをまとめて見せる場所
  const summary = document.createElement("section");
  summary.className = "question-summary";
  summary.innerHTML = "<p><strong>答えを確かめてください</strong></p><dl></dl>";
  form.insertBefore(summary, submit);

  const makeButton = (text, className) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = text;
    if (className) button.className = className;
    return button;
  };

  let current = 0;
  const show = (index) => {
    current = index;
    steps.forEach((step, i) => {
      step.hidden = i !== index;
    });
    const atSummary = index === steps.length;
    summary.hidden = !atSummary;
    submit.hidden = !atSummary;
    if (atSummary) {
      const list = summary.querySelector("dl");
      list.replaceChildren();
      steps.forEach((step, i) => {
        const dt = document.createElement("dt");
        dt.textContent = step.querySelector("label").textContent.trim();
        const dd = document.createElement("dd");
        dd.textContent = answerOf(step).value.trim() || "（まだ答えていません）";
        const fix = makeButton("直す", "link-button");
        fix.addEventListener("click", () => show(i));
        dd.append(" ", fix);
        list.append(dt, dd);
      });
      summary.scrollIntoView({ block: "nearest" });
    } else {
      answerOf(steps[index]).focus({ preventScroll: true });
    }
  };

  steps.forEach((step, i) => {
    const textarea = answerOf(step);
    const message = document.createElement("small");
    message.className = "step-message";
    message.setAttribute("aria-live", "polite");
    const nav = document.createElement("div");
    nav.className = "step-nav";
    if (i > 0) {
      const back = makeButton("戻る", "secondary outline");
      back.addEventListener("click", () => show(i - 1));
      nav.append(back);
    }
    const next = makeButton(i === steps.length - 1 ? "答えを確かめる" : "次へ");
    const goNext = () => {
      if (!textarea.value.trim()) {
        message.textContent = step.querySelector("[data-choice]")
          ? "選択肢を選ぶか、答えを入力してください。"
          : "答えを入力してください。";
        textarea.focus();
        return;
      }
      message.textContent = "";
      show(i + 1);
    };
    next.addEventListener("click", goNext);
    nav.append(next);
    step.append(message, nav);

    // 選択肢を押すと、その言葉を答えの欄に入れて、次の質問へ進む
    step.querySelectorAll("[data-choice]").forEach((chip) => {
      chip.addEventListener("click", () => {
        textarea.value = chip.dataset.choice;
        step.querySelectorAll("[data-choice]").forEach((other) => {
          other.classList.toggle("outline", other !== chip);
          other.setAttribute("aria-pressed", String(other === chip));
        });
        setTimeout(goNext, 250);
      });
    });
  });

  // 最初に出す質問：入力の誤りがある質問、まだ答えていない質問、どちらも無ければ確かめる画面
  const invalid = steps.findIndex((step) => answerOf(step).getAttribute("aria-invalid") === "true");
  const empty = steps.findIndex((step) => !answerOf(step).value.trim());
  const start = invalid >= 0 ? invalid : empty >= 0 ? empty : steps.length;
  // 最初の表示では、質問の欄にフォーカスを移さない（画面が飛ばないように）
  steps.forEach((step, i) => {
    step.hidden = i !== start;
  });
  summary.hidden = start !== steps.length;
  submit.hidden = start !== steps.length;
  current = start;
  if (start === steps.length) show(start);
})();
