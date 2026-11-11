const form = document.querySelector("#topic-form");
const results = document.querySelector("#results");
const submit = document.querySelector("#submit");
const modePill = document.querySelector("#mode-pill");
const profession = document.querySelector("#profession");
const levelFields = document.querySelector("#level-fields");
const levelInputs = [...document.querySelectorAll('input[name="level"]')];
const studyFields = document.querySelector("#study-fields");
const generationFields = document.querySelector("#generation-fields");
const studied = document.querySelector("#studied");
const suggestions = document.querySelector("#subject-suggestions");
const instituteBadge = document.querySelector("#institute-badge");
const lessonFile = document.querySelector("#lesson-file");
const uploadStatus = document.querySelector("#upload-status");
const selectedSuggestions = new Set();

const catalogResponse = await fetch("/static/catalog.json");
if (!catalogResponse.ok) throw new Error("Не удалось загрузить список программ университета");
const { programs, studyExamples } = await catalogResponse.json();

const groups = [...new Set(programs.map(program => program[0]))];
for (const group of groups) {
  const optgroup = document.createElement("optgroup");
  optgroup.label = group;
  programs.filter(program => program[0] === group).forEach(program => {
    const option = document.createElement("option");
    option.value = program[1];
    option.textContent = `${program[1]} — ${program[2]}`;
    option.dataset.institute = program[0];
    option.dataset.program = program[2];
    option.dataset.family = program[3];
    optgroup.appendChild(option);
  });
  profession.appendChild(optgroup);
}

function renderSubjectSuggestions() {
  const selected = programs.find(program => program[1] === profession.value);
  if (!selected) {
    levelFields.hidden = true;
    studyFields.hidden = true;
    generationFields.hidden = true;
    studied.required = false;
    submit.disabled = true;
    return;
  }
  document.querySelector("#major-payload").value = selected[2];
  levelFields.hidden = false;
  const hasLevel = levelInputs.some(input => input.checked);
  studyFields.hidden = !hasLevel;
  generationFields.hidden = !hasLevel;
  studied.required = hasLevel;
  if (!hasLevel) {
    submit.disabled = true;
    return;
  }
  instituteBadge.textContent = selected[0];
  suggestions.innerHTML = (studyExamples[selected[3]] || []).map(topic =>
    `<button type="button" class="subject-chip" aria-pressed="false">${escapeHtml(topic)}<span>＋</span></button>`
  ).join("");
  suggestions.querySelectorAll(".subject-chip").forEach(button => {
    button.addEventListener("click", () => {
      const topic = button.firstChild.textContent.trim();
      const lines = studied.value.split("\n").map(line => line.trim()).filter(Boolean);
      if (selectedSuggestions.has(topic)) {
        selectedSuggestions.delete(topic);
        studied.value = lines.filter(line => line !== topic).join("\n");
        button.classList.remove("selected");
        button.setAttribute("aria-pressed", "false");
        button.querySelector("span").textContent = "＋";
      } else {
        selectedSuggestions.add(topic);
        if (!lines.includes(topic)) studied.value = [...lines, topic].join("\n");
        button.classList.add("selected");
        button.setAttribute("aria-pressed", "true");
        button.querySelector("span").textContent = "✓";
      }
      updateSubmitState();
    });
  });
  for (const button of suggestions.querySelectorAll(".subject-chip")) {
    const topic = button.firstChild.textContent.trim();
    if (selectedSuggestions.has(topic)) {
      button.classList.add("selected");
      button.setAttribute("aria-pressed", "true");
      button.querySelector("span").textContent = "✓";
    }
  }
  updateSubmitState();
}

profession.addEventListener("change", () => {
  const lines = studied.value.split("\n").map(line => line.trim()).filter(Boolean);
  studied.value = lines.filter(line => !selectedSuggestions.has(line)).join("\n");
  selectedSuggestions.clear();
  levelInputs.forEach(input => { input.checked = false; });
  renderSubjectSuggestions();
});

levelInputs.forEach(input => input.addEventListener("change", renderSubjectSuggestions));
studied.addEventListener("input", updateSubmitState);

lessonFile.addEventListener("change", async () => {
  const file = lessonFile.files?.[0];
  if (!file) return;
  if (file.size > 6 * 1024 * 1024) {
    uploadStatus.textContent = "Файл больше 6 МБ. Выбери документ меньшего размера.";
    uploadStatus.className = "upload-status error";
    lessonFile.value = "";
    return;
  }
  uploadStatus.textContent = "Читаю документ…";
  uploadStatus.className = "upload-status";
  const formData = new FormData();
  formData.append("document", file);
  try {
    const response = await fetch("/api/extract-document", {method: "POST", body: formData});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Не удалось прочитать документ.");
    const current = studied.value.trim();
    studied.value = current ? `${current}\n${data.text}` : data.text;
    updateSubmitState();
    uploadStatus.textContent = `Добавлено из файла «${data.filename}»`;
    uploadStatus.className = "upload-status success";
  } catch (error) {
    uploadStatus.textContent = error.message;
    uploadStatus.className = "upload-status error";
  } finally {
    lessonFile.value = "";
  }
});

function updateSubmitState() {
  submit.disabled = !profession.value || !levelInputs.some(input => input.checked) || !studied.value.trim();
}

const escapeHtml = (value = "") => String(value).replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));

function renderTopics(topics) {
  results.innerHTML = topics.map((topic, index) => `
    <article class="topic-card">
      <div class="topic-meta"><span>ИДЕЯ ${String(index + 1).padStart(2, "0")}</span><button class="copy-button" type="button" data-title="${escapeHtml(topic.title)}" aria-label="Скопировать название">↗</button></div>
      <h3>${escapeHtml(topic.title)}</h3>
      <p class="topic-why">${escapeHtml(topic.why)}</p>
      <details><summary>Цель и задачи <span>＋</span></summary><div class="detail-body"><b>Цель</b><p>${escapeHtml(topic.goal)}</p><b>Задачи</b><ol>${(topic.tasks || []).map(task => `<li>${escapeHtml(task)}</li>`).join("")}</ol><b>Ожидаемый результат</b><p>${escapeHtml(topic.result)}</p></div></details>
    </article>`).join("");
  results.querySelectorAll(".copy-button").forEach(button => button.addEventListener("click", async () => {
    await navigator.clipboard.writeText(button.dataset.title);
    button.textContent = "✓";
    setTimeout(() => button.textContent = "↗", 1400);
  }));
}

form.addEventListener("submit", async event => {
  event.preventDefault();
  submit.disabled = true;
  submit.querySelector("span:first-child").textContent = "Подбираю идеи…";
  modePill.textContent = "ДУМАЮ";
  modePill.className = "mode-pill thinking";
  results.innerHTML = `<div class="loading-state"><div class="loader"></div><h3>Связываю темы<br>в новые идеи</h3><p>Это займёт несколько секунд</p></div>`;
  const payload = Object.fromEntries(new FormData(form).entries());
  try {
    const response = await fetch("/api/generate", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Не удалось сгенерировать темы.");
    renderTopics(data.topics);
    modePill.textContent = data.mode === "ai" ? "СГЕНЕРИРОВАНО ИИ" : "ДЕМО-РЕЖИМ";
    modePill.className = `mode-pill ${data.mode === "ai" ? "ai" : "demo"}`;
  } catch (error) {
    results.innerHTML = `<div class="error-state"><span>!</span><h3>Не получилось получить идеи</h3><p>${escapeHtml(error.message)}</p><button type="button" class="retry">Попробовать ещё раз</button></div>`;
    modePill.textContent = "ОШИБКА";
    modePill.className = "mode-pill error";
    results.querySelector(".retry").addEventListener("click", () => form.requestSubmit());
  } finally {
    updateSubmitState();
    submit.querySelector("span:first-child").textContent = "Подобрать темы";
  }
});
