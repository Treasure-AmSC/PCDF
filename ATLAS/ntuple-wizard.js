    const OBJECTS = JSON.parse(document.getElementById("object-config").textContent);

    const OPEN_DATA_API_BASE = "https://atlasopenmagic-api.app.cern.ch";
    const OPEN_DATA_PREVIEW_PROXY = "https://api.allorigins.win/raw?url=";
    const OPEN_DATA_RELEASE = "2024r-pp";
    const OPEN_DATA_SKIM = "noskim";
    const OPEN_DATA_DTN_PATTERN = "dtn";

    const state = {
      step: 0,
      inputFormat: "TREASURE",
      selectedObjects: new Set(Object.keys(OBJECTS).filter((key) => OBJECTS[key].recommended)),
      selectedVariables: Object.fromEntries(Object.entries(OBJECTS).map(([key, object]) => [key, new Set(Object.keys(object.aliases))])),
      slurm: {
        enabled: true,
        account: "<NERSC_PROJECT>",
        qos: "regular",
        nodes: 1,
        jobsPerNode: 8,
        time: "02:00:00",
        pythonPath: "ntuple-maker.py",
        inputManifest: "$SCRATCH/pcdf-inputs.txt",
        openDataRelease: OPEN_DATA_RELEASE,
        openDataQuery: "",
        openDataDataset: "data",
        openDataSkim: OPEN_DATA_SKIM,
        openDataDownloadDir: "$SCRATCH/pcdf-opendata",
        openDataDtnPattern: OPEN_DATA_DTN_PATTERN,
        openDataMbps: 250,
        openDataPreview: null,
        outputBase: "$SCRATCH/pcdf-output"
      }
    };

    const objectList = document.getElementById("objectList");
    const variableAccordion = document.getElementById("variableAccordion");
    const scriptOutput = document.getElementById("scriptOutput");
    const scriptHighlight = document.getElementById("scriptHighlight").querySelector("code");
    const slurmScriptOutput = document.getElementById("slurmScriptOutput");
    const slurmScriptHighlight = document.getElementById("slurmScriptHighlight").querySelector("code");
    const transferScriptOutput = document.getElementById("transferScriptOutput");
    const openDataPreview = document.getElementById("openDataPreview");
    const openDataDatasetOptions = document.getElementById("openDataDatasetOptions");
    const summary = document.getElementById("summary");

    const TEMPLATE_IDS = {
      python: "template-python",
      slurm: "template-slurm",
      transfer: "template-transfer",
      readme: "template-readme",
    };

    const templates = {};


    function loadTemplates() {
      Object.entries(TEMPLATE_IDS).forEach(([name, id]) => {
        const element = document.getElementById(id);
        if (!element) throw new Error(`Missing embedded template: ${id}`);
        templates[name] = element.textContent.trimStart();
      });
    }

    function applyTemplate(template, values) {
      return template.replace(/{{([A-Z0-9_]+)}}/g, (match, key) => {
        if (!Object.hasOwn(values, key)) {
          throw new Error(`Missing template value: ${key}`);
        }
        return values[key];
      });
    }

    function requireTemplate(name) {
      if (!templates[name]) {
        throw new Error(`Template not loaded: ${name}`);
      }
      return templates[name];
    }

    function fieldValue(id) {
      return document.getElementById(id).value.trim();
    }

    function numericFieldValue(id, fallback) {
      const value = Number.parseInt(fieldValue(id), 10);
      return Number.isFinite(value) && value > 0 ? value : fallback;
    }

    function syncSlurmSettings() {
      state.slurm.enabled = document.getElementById("enableSlurm").checked;
      state.slurm.account = fieldValue("slurmAccount") || "<NERSC_PROJECT>";
      state.slurm.qos = fieldValue("slurmQos") || "regular";
      state.slurm.nodes = numericFieldValue("slurmNodes", 1);
      state.slurm.jobsPerNode = Math.min(numericFieldValue("slurmJobsPerNode", 8), 128);
      document.getElementById("slurmJobsPerNode").value = state.slurm.jobsPerNode;
      state.slurm.time = fieldValue("slurmTime") || "02:00:00";
      state.slurm.pythonPath = fieldValue("slurmPythonPath") || "ntuple-maker.py";
      state.slurm.inputManifest = fieldValue("slurmInputManifest") || "$SCRATCH/pcdf-inputs.txt";
      state.slurm.openDataRelease = OPEN_DATA_RELEASE;
      state.slurm.openDataQuery = fieldValue("openDataQuery");
      state.slurm.openDataDataset = fieldValue("openDataDataset") || "data";
      state.slurm.openDataSkim = OPEN_DATA_SKIM;
      state.slurm.openDataDownloadDir = fieldValue("openDataDownloadDir") || "$SCRATCH/pcdf-opendata";
      state.slurm.openDataDtnPattern = OPEN_DATA_DTN_PATTERN;
      state.slurm.openDataMbps = numericFieldValue("openDataMbps", 250);
      state.slurm.outputBase = fieldValue("slurmOutputBase") || "$SCRATCH/pcdf-output";
    }

    function selectedInputFormat() {
      return document.querySelector("input[name='inputFormat']:checked").value;
    }

    function isObjectAvailable(key) {
      return !(OBJECTS[key].requiresTreasure && state.inputFormat === "PHYSLITE");
    }

    function dependenciesFor(key) {
      return OBJECTS[key].dependsOn || [];
    }

    function addDependencies(key) {
      dependenciesFor(key).forEach((dependency) => {
        if (isObjectAvailable(dependency)) {
          state.selectedObjects.add(dependency);
          addDependencies(dependency);
        }
      });
    }

    function dependentObjectsFor(key) {
      return Object.keys(OBJECTS).filter((candidate) => dependenciesFor(candidate).includes(key));
    }

    function removeDependents(key) {
      dependentObjectsFor(key).forEach((dependent) => {
        if (state.selectedObjects.delete(dependent)) {
          removeDependents(dependent);
        }
      });
    }

    function requiredVariablesFor(key) {
      return new Set(OBJECTS[key].requiredVariables || []);
    }

    function variableIsRequired(key, name) {
      return requiredVariablesFor(key).has(name);
    }

    function dependencyBadges(key) {
      const dependents = dependentObjectsFor(key).filter((dependent) => state.selectedObjects.has(dependent));
      const dependencies = dependenciesFor(key).filter((dependency) => state.selectedObjects.has(dependency));
      const badges = [];
      if (dependencies.length) {
        const dependencyNames = dependencies.map((dependency) => OBJECTS[dependency].title).join(", ");
        badges.push(`<span class="badge text-bg-info" title="Uses ${dependencyNames}">Requires ${dependencies.length === 1 ? OBJECTS[dependencies[0]].title : `${dependencies.length} objects`}</span>`);
      }
      if (dependents.length) {
        const dependentNames = dependents.map((dependent) => OBJECTS[dependent].title).join(", ");
        badges.push(`<span class="badge text-bg-warning" title="Deselecting this also removes ${dependentNames}">${dependents.length} dependent${dependents.length === 1 ? "" : "s"}</span>`);
      }
      return badges.join("");
    }

    function renderObjects() {
      objectList.innerHTML = Object.entries(OBJECTS).map(([key, object]) => {
        const disabled = !isObjectAvailable(key);
        const checked = state.selectedObjects.has(key) && !disabled;
        const dependents = dependentObjectsFor(key).filter((dependent) => state.selectedObjects.has(dependent));
        const deselectHint = checked && dependents.length
          ? `Turning this off also removes ${dependents.map((dependent) => OBJECTS[dependent].title).join(", ")}.`
          : object.requiredReason || "";
        return `
          <div class="col-md-6 col-xl-4">
            <label class="card object-card h-100 border-secondary-subtle ${disabled ? "opacity-50" : ""}">
              <div class="card-body">
                <div class="form-check form-switch mb-2">
                  <input class="form-check-input object-toggle" type="checkbox" value="${key}" ${checked ? "checked" : ""} ${disabled ? "disabled" : ""}>
                  <span class="form-check-label fw-semibold">${object.title}</span>
                </div>
                <p class="small text-secondary mb-2">${object.description}</p>
                <div class="object-meta">
                  <span class="badge text-bg-secondary">${Object.keys(object.aliases).length} variables</span>
                  ${dependencyBadges(key)}
                  ${disabled ? '<span class="badge text-bg-warning">Unavailable in PHYSLITE</span>' : ""}
                </div>
                ${deselectHint ? `<span class="d-block small dependency-note mt-2">${deselectHint}</span>` : ""}
              </div>
            </label>
          </div>`;
      }).join("");

      objectList.querySelectorAll(".object-toggle").forEach((input) => {
        input.addEventListener("change", () => {
          if (input.checked) {
            state.selectedObjects.add(input.value);
            addDependencies(input.value);
          } else if (input.value === "Event") {
            state.selectedObjects = new Set(["Event"]);
          } else {
            state.selectedObjects.delete(input.value);
            removeDependents(input.value);
          }
          ensureDependencies();
          renderObjects();
          renderVariables();
          updateGeneratedScript();
        });
      });
    }

    function renderVariables() {
      const selected = Object.keys(OBJECTS).filter((key) => state.selectedObjects.has(key) && isObjectAvailable(key));
      variableAccordion.innerHTML = selected.length ? selected.map((key, index) => {
        const object = OBJECTS[key];
        const variables = Object.entries(object.aliases).map(([name, branch]) => {
          const branchText = Array.isArray(branch) ? branch.join(" / ") : branch;
          const required = variableIsRequired(key, name);
          if (required) state.selectedVariables[key].add(name);
          return `
            <div class="form-check mb-2">
              <input class="form-check-input variable-toggle" type="checkbox" value="${name}" data-object="${key}" id="var-${key}-${name}" ${state.selectedVariables[key].has(name) ? "checked" : ""} ${required ? "disabled" : ""}>
              <label class="form-check-label" for="var-${key}-${name}">
                <span class="fw-semibold">${name}</span>
                ${required ? '<span class="badge text-bg-warning ms-1">required vector component</span>' : ""}
                <span class="d-block small text-secondary">${branchText}</span>
              </label>
            </div>`;
        }).join("");
        return `
          <div class="accordion-item">
            <h3 class="accordion-header">
              <button class="accordion-button ${index ? "collapsed" : ""}" type="button" data-bs-toggle="collapse" data-bs-target="#panel-${key}">
                ${object.title}
              </button>
            </h3>
            <div id="panel-${key}" class="accordion-collapse collapse ${index ? "" : "show"}" data-bs-parent="#variableAccordion">
              <div class="accordion-body variable-grid">${variables}</div>
            </div>
          </div>`;
      }).join("") : '<div class="alert alert-warning">Select at least one output object before choosing variables.</div>';

      variableAccordion.querySelectorAll(".variable-toggle").forEach((input) => {
        input.addEventListener("change", () => {
          const variables = state.selectedVariables[input.dataset.object];
          if (variableIsRequired(input.dataset.object, input.value)) {
            variables.add(input.value);
            input.checked = true;
          } else {
            input.checked ? variables.add(input.value) : variables.delete(input.value);
            if (variables.size === 0) {
              variables.add(input.value);
              input.checked = true;
            }
          }
          updateGeneratedScript();
        });
      });
    }

    function ensureDependencies() {
      if (state.inputFormat === "PHYSLITE") {
        state.selectedObjects.delete("Const");
      }
      Array.from(state.selectedObjects).forEach((key) => {
        if (!isObjectAvailable(key)) {
          state.selectedObjects.delete(key);
          removeDependents(key);
        } else {
          addDependencies(key);
        }
      });
      state.selectedObjects.add("Event");
      Object.keys(OBJECTS).forEach((key) => {
        requiredVariablesFor(key).forEach((name) => state.selectedVariables[key].add(name));
      });
    }

    function setStep(step) {
      state.step = Math.max(0, Math.min(3, step));
      document.querySelectorAll(".wizard-step").forEach((section) => {
        section.classList.toggle("d-none", Number(section.dataset.step) !== state.step);
      });
      document.querySelectorAll("[data-step-target]").forEach((button) => {
        button.classList.toggle("active", Number(button.dataset.stepTarget) === state.step);
      });
      document.getElementById("prevStep").disabled = state.step === 0;
      document.getElementById("nextStep").textContent = state.step === 3 ? "Regenerate" : "Next";
      if (state.step === 3) updateGeneratedScript();
    }

    function selectedVariables(key) {
      return Array.from(state.selectedVariables[key] || []).filter((name) => Object.hasOwn(OBJECTS[key].aliases, name));
    }

    function escapeHtml(value) {
      return value
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;");
    }

    function highlightPython(code) {
      const tokenPattern = /("""[\s\S]*?"""|'''[\s\S]*?'''|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|#[^\n]*|\b(?:False|None|True|and|as|class|continue|def|elif|else|except|finally|for|from|if|import|in|is|not|or|pass|raise|return|try|while|with)\b|\b(?:ak|click|dict|exit|int|len|list|print|range|str|zip)\b|\b\d+(?:\.\d+)?\b)/g;
      let highlighted = "";
      let cursor = 0;
      for (const match of code.matchAll(tokenPattern)) {
        highlighted += escapeHtml(code.slice(cursor, match.index));
        const token = match[0];
        let className = "syntax-number";
        if (token.startsWith("#")) className = "syntax-comment";
        else if (token.startsWith('"') || token.startsWith("'")) className = "syntax-string";
        else if (/^(ak|click|dict|exit|int|len|list|print|range|str|zip)$/.test(token)) className = "syntax-builtin";
        else if (/^[A-Za-z_]+$/.test(token)) className = "syntax-keyword";
        highlighted += `<span class="${className}">${escapeHtml(token)}</span>`;
        cursor = match.index + token.length;
      }
      highlighted += escapeHtml(code.slice(cursor));
      return highlighted;
    }

    function formatBytes(bytes) {
      if (!Number.isFinite(bytes) || bytes <= 0) return "unknown size";
      const units = ["B", "KB", "MB", "GB", "TB", "PB"];
      let value = bytes;
      let unit = 0;
      while (value >= 1000 && unit < units.length - 1) {
        value /= 1000;
        unit += 1;
      }
      return `${value >= 10 || unit === 0 ? value.toFixed(0) : value.toFixed(1)} ${units[unit]}`;
    }

    function formatDuration(seconds) {
      if (!Number.isFinite(seconds) || seconds <= 0) return "unknown";
      const hours = Math.floor(seconds / 3600);
      const minutes = Math.floor((seconds % 3600) / 60);
      const secs = Math.round(seconds % 60);
      if (hours) return `${hours} h ${minutes} min`;
      if (minutes) return `${minutes} min ${secs} s`;
      return `${secs} s`;
    }

    function applyHttpsProtocol(url) {
      return String(url).replace(
        "root://eospublic.cern.ch:1094/",
        "https://opendata.cern.ch"
      );
    }

    function availableFileLists(metadata) {
      const lists = new Map();
      if (Array.isArray(metadata.file_list) && metadata.file_list.length) {
        lists.set("noskim", metadata.file_list);
      }
      (metadata.skims || []).forEach((skim) => {
        if (skim.skim_type && Array.isArray(skim.file_list) && skim.file_list.length) {
          lists.set(skim.skim_type, skim.file_list);
        }
      });
      return lists;
    }

    async function headContentLength(url) {
      try {
        const response = await fetch(url, { method: "HEAD" });
        if (!response.ok) return 0;
        return Number.parseInt(response.headers.get("content-length") || "0", 10) || 0;
      } catch (error) {
        return 0;
      }
    }

    function apiBaseUrl() {
      return OPEN_DATA_API_BASE.replace(/\/$/, "");
    }

    function datasetSearchText(dataset) {
      return [
        dataset.dataset_number,
        dataset.physics_short,
        dataset.process,
        dataset.description,
        dataset.job_path,
        dataset.Release,
        dataset["release.name"],
        ...(dataset.keywords || []),
      ].filter(Boolean).join(" ").toLowerCase();
    }

    function isResearchPhysliteDataset(dataset) {
      // atlasopenmagic's 2024r-pp release is the research proton-proton
      // PHYSLITE release. Keep the check explicit so later release choices do
      // not silently mix in education, heavy-ion, or event-generation data.
      return state.slurm.openDataRelease === "2024r-pp" &&
        Array.isArray(dataset.file_list) && dataset.file_list.length;
    }

    function datasetMatchesQuery(dataset, query) {
      const normalized = query.trim().toLowerCase();
      if (!normalized || normalized === "physlite") return true;
      return datasetSearchText(dataset).includes(normalized);
    }

    function datasetMatchesKey(dataset, key) {
      const normalized = String(key || "").trim().toLowerCase();
      if (!normalized) return false;
      return String(dataset.dataset_number || "").toLowerCase() === normalized ||
        String(dataset.physics_short || "").toLowerCase() === normalized;
    }

    function openDataApiUrl(path, params = {}) {
      const url = new URL(`${apiBaseUrl()}${path}`);
      Object.entries(params).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== "") {
          url.searchParams.set(key, value);
        }
      });
      return url;
    }

    function previewProxyUrl(url) {
      const proxy = OPEN_DATA_PREVIEW_PROXY;
      if (!proxy) return null;
      return `${proxy}${encodeURIComponent(url.toString())}`;
    }

    async function fetchJsonUrl(url) {
      const response = await fetch(url, { headers: { Accept: "application/json" } });
      if (!response.ok) throw new Error(`API returned HTTP ${response.status}`);
      return response.json();
    }

    async function fetchOpenDataJson(path, params = {}) {
      const url = openDataApiUrl(path, params);
      try {
        return await fetchJsonUrl(url);
      } catch (error) {
        const fallback = previewProxyUrl(url);
        if (!fallback) throw error;
        return fetchJsonUrl(fallback);
      }
    }

    async function fetchResearchDatasets() {
      const releaseName = state.slurm.openDataRelease;
      const limit = 1000;
      let total = limit;
      try {
        const count = await fetchOpenDataJson("/datasets/count", { release_name: releaseName });
        total = Number.parseInt(count.count || count, 10) || limit;
      } catch (error) {
        total = limit;
      }
      const pages = [];
      for (let skip = 0; skip < total; skip += limit) {
        pages.push(fetchOpenDataJson("/datasets", {
          release_name: releaseName,
          skip,
          limit,
        }));
      }
      return (await Promise.all(pages)).flat().filter(isResearchPhysliteDataset);
    }

    function renderDatasetMatches(matches) {
      openDataDatasetOptions.innerHTML = matches.slice(0, 50).map((dataset) => {
        const label = [dataset.dataset_number, dataset.physics_short].filter(Boolean).join(" — ");
        return `<option value="${escapeHtml(String(dataset.dataset_number || dataset.physics_short))}">${escapeHtml(label)}</option>`;
      }).join("");
      if (!matches.length) return "No matching 2024r-pp PHYSLITE research datasets found.";
      const rows = matches.slice(0, 8).map((dataset) => {
        const key = String(dataset.dataset_number || dataset.physics_short);
        const title = escapeHtml(dataset.physics_short || dataset.process || key);
        const desc = escapeHtml(dataset.process || dataset.description || "research PHYSLITE dataset");
        return `<li><button class="btn btn-sm btn-outline-light open-data-choice" type="button" data-dataset="${escapeHtml(key)}">Use ${escapeHtml(key)}</button> <strong>${title}</strong><span class="d-block small text-secondary">${desc}</span></li>`;
      }).join("");
      return `<p class="mb-2">Found ${matches.length} matching 2024r-pp research PHYSLITE dataset(s). Showing the first ${Math.min(matches.length, 8)}:</p><ol class="mb-0 ps-3">${rows}</ol>`;
    }

    async function previewSelectedOpenDataDataset() {
      const slurm = state.slurm;
      const metadata = await fetchOpenDataJson(
        `/metadata/${encodeURIComponent(slurm.openDataRelease)}/${encodeURIComponent(slurm.openDataDataset)}`
      );
      const lists = availableFileLists(metadata);
      const files = lists.get(slurm.openDataSkim);
      if (!files || !files.length) {
        const choices = Array.from(lists.keys()).sort().join(", ") || "none";
        throw new Error(`Skim '${slurm.openDataSkim}' has no files. Available: ${choices}.`);
      }
      const urls = files.map(applyHttpsProtocol);
      const headSample = urls.slice(0, Math.min(urls.length, 8));
      const sizes = await Promise.all(headSample.map(headContentLength));
      const sizedFiles = sizes.filter(Boolean).length;
      const knownBytes = sizes.reduce((sum, value) => sum + value, 0);
      const avgBytes = sizedFiles ? knownBytes / sizedFiles : 0;
      const estimatedBytes = avgBytes ? Math.round(avgBytes * urls.length) : 0;
      const seconds = estimatedBytes / (Math.max(slurm.openDataMbps, 1) * 1000 * 1000);
      state.slurm.openDataPreview = {
        files: urls.length,
        bytes: estimatedBytes,
        sizedFiles,
        seconds,
      };
      return { files: urls.length, estimatedBytes, sizedFiles, seconds };
    }

    async function lookupOpenDataPreview() {
      syncSlurmSettings();
      const slurm = state.slurm;
      openDataPreview.className = "alert alert-info open-data-preview mt-3 mb-0";
      openDataPreview.textContent = "Searching 2024r-pp research PHYSLITE datasets…";
      try {
        const query = slurm.openDataQuery;
        const datasets = await fetchResearchDatasets();
        const matches = datasets.filter((dataset) => datasetMatchesQuery(dataset, query));
        const exact = datasets.find((dataset) => datasetMatchesKey(dataset, slurm.openDataDataset));
        const selected = exact || matches[0];
        if (!selected) throw new Error("No matching 2024r-pp research PHYSLITE datasets found.");
        state.slurm.openDataDataset = String(selected.dataset_number || selected.physics_short);
        document.getElementById("openDataDataset").value = state.slurm.openDataDataset;
        const preview = await previewSelectedOpenDataDataset();
        openDataPreview.className = "alert alert-success open-data-preview mt-3 mb-0";
        openDataPreview.innerHTML = `
          <strong>${escapeHtml(slurm.openDataRelease)}/${escapeHtml(state.slurm.openDataDataset)}</strong>
          (${escapeHtml(slurm.openDataSkim)}) has ${preview.files} file(s).<br>
          Estimated download: ${formatBytes(preview.estimatedBytes)} from ${preview.sizedFiles}
          sampled HEAD response(s).<br>
          At ${slurm.openDataMbps} MB/s, transfer time is about ${formatDuration(preview.seconds)}.
          Actual DTN throughput and scratch I/O can differ.
          <hr class="my-2">${renderDatasetMatches(matches)}
        `;
        openDataPreview.querySelectorAll(".open-data-choice").forEach((button) => {
          button.addEventListener("click", () => {
            document.getElementById("openDataDataset").value = button.dataset.dataset;
            state.slurm.openDataDataset = button.dataset.dataset;
            lookupOpenDataPreview();
          });
        });
        updateGeneratedScript();
      } catch (error) {
        state.slurm.openDataPreview = null;
        openDataPreview.className = "alert alert-warning open-data-preview mt-3 mb-0";
        openDataPreview.textContent = `Preview unavailable: ${error.message}. ` +
          "The DTN transfer script will perform the same API lookup before downloading.";
        updateGeneratedScript();
      }
    }

    function selectedConfig() {
      const objects = Object.fromEntries(Object.entries(OBJECTS)
        .filter(([key]) => state.selectedObjects.has(key) && isObjectAvailable(key))
        .map(([key, object]) => [key, {
          folder: object.folder,
          index_name: object.indexName || null,
          aliases: Object.fromEntries(selectedVariables(key).map((name) => [name, object.aliases[name]]))
        }]));
      return { inputFormat: state.inputFormat, objects };
    }


    function splitPythonString(value, indent) {
      const prefix = " ".repeat(indent + 4);
      const chunks = [];
      let remaining = value;
      while (remaining.length > 38) {
        let splitAt = remaining.lastIndexOf(".", 38);
        if (splitAt < 12) splitAt = 38;
        chunks.push(remaining.slice(0, splitAt + (remaining[splitAt] === "." ? 1 : 0)));
        remaining = remaining.slice(chunks.at(-1).length);
      }
      if (remaining) chunks.push(remaining);
      return `(\n${chunks.map((chunk) => `${prefix}${JSON.stringify(chunk)}`).join("\n")}\n${" ".repeat(indent)})`;
    }

    function formatPythonLiteral(value, indent = 0) {
      const pad = " ".repeat(indent);
      if (value === null) return "None";
      if (typeof value === "string") {
        const quoted = JSON.stringify(value);
        return quoted.length > 28 ? splitPythonString(value, indent) : quoted;
      }
      if (Array.isArray(value)) {
        if (!value.length) return "[]";
        return `[\n${value.map((item) => `${" ".repeat(indent + 4)}${formatPythonLiteral(item, indent + 4)}`).join(",\n")}\n${pad}]`;
      }
      if (typeof value === "object") {
        const entries = Object.entries(value);
        if (!entries.length) return "{}";
        const lines = entries.map(([key, item]) => {
          return `${" ".repeat(indent + 4)}${JSON.stringify(key)}: ${formatPythonLiteral(item, indent + 4)}`;
        });
        return `{\n${lines.join(",\n")}\n${pad}}`;
      }
      return String(value);
    }

    function buildScript() {
      const config = selectedConfig();
      const objectConfig = formatPythonLiteral(config.objects);
      const inputNote = config.inputFormat === "PHYSLITE"
        ? "PHYSLITE selected: jet constituents are disabled."
        : "TREASURE selected: jet constituents can be read.";
      return applyTemplate(requireTemplate("python"), {
        INPUT_FORMAT: config.inputFormat,
        INPUT_NOTE: inputNote,
        OBJECTS: objectConfig,
      });
    }

    function openDataExpectedBytes() {
      return state.slurm.openDataPreview?.bytes || 0;
    }

    function openDataExpectedFiles() {
      return state.slurm.openDataPreview?.files || 0;
    }

    function commonBatchValues() {
      const slurm = state.slurm;
      return {
        PYTHON_PATH: JSON.stringify(slurm.pythonPath),
        INPUT_MANIFEST: JSON.stringify(slurm.inputManifest),
        OUTPUT_BASE: JSON.stringify(slurm.outputBase),
        OPEN_DATA_API_BASE: JSON.stringify(OPEN_DATA_API_BASE),
        OPEN_DATA_RELEASE: JSON.stringify(slurm.openDataRelease),
        OPEN_DATA_QUERY: JSON.stringify(slurm.openDataQuery),
        OPEN_DATA_DATASET: JSON.stringify(slurm.openDataDataset),
        OPEN_DATA_SKIM: JSON.stringify(OPEN_DATA_SKIM),
        OPEN_DATA_DOWNLOAD_DIR: JSON.stringify(slurm.openDataDownloadDir),
        OPEN_DATA_DTN_PATTERN: JSON.stringify(slurm.openDataDtnPattern),
        OPEN_DATA_EXPECTED_BYTES: openDataExpectedBytes(),
        OPEN_DATA_EXPECTED_FILES: openDataExpectedFiles(),
        OPEN_DATA_EXPECTED_MBPS: slurm.openDataMbps,
      };
    }

    function buildSlurmScript() {
      const slurm = state.slurm;
      const accountLine = slurm.account
        ? `#SBATCH --account=${slurm.account}`
        : "#SBATCH --account=<NERSC_PROJECT>";
      const perlmutterCpuCores = 128;
      return applyTemplate(requireTemplate("slurm"), {
        ...commonBatchValues(),
        ACCOUNT_LINE: accountLine,
        QOS: slurm.qos,
        NODES: slurm.nodes,
        PERLMUTTER_CPU_CORES: perlmutterCpuCores,
        TIME: slurm.time,
        JOBS_PER_NODE: slurm.jobsPerNode,
      });
    }

    function buildTransferScript() {
      return applyTemplate(requireTemplate("transfer"), commonBatchValues());
    }

    function updateGeneratedScript() {
      syncSlurmSettings();
      ensureDependencies();
      const config = selectedConfig();
      const generatedScript = buildScript();
      const slurmScript = buildSlurmScript();
      const transferScript = buildTransferScript();
      scriptOutput.value = generatedScript;
      scriptHighlight.innerHTML = highlightPython(generatedScript);
      slurmScriptOutput.value = slurmScript;
      transferScriptOutput.value = transferScript;
      slurmScriptHighlight.innerHTML = state.slurm.enabled ? highlightPython(slurmScript) : "SLURM wrapper disabled.";
      document.getElementById("downloadSlurmScript").disabled = !state.slurm.enabled;
      summary.innerHTML = `
        <div class="card border-secondary-subtle"><div class="card-body">
          <h3 class="h6 text-uppercase text-secondary">Input</h3>
          <p class="mb-0 fw-semibold">${config.inputFormat}</p>
        </div></div>
        <div class="card border-secondary-subtle"><div class="card-body">
          <h3 class="h6 text-uppercase text-secondary">Objects</h3>
          <ul class="mb-0">${Object.keys(config.objects).map((key) => `<li>${OBJECTS[key].title}: ${Object.keys(config.objects[key].aliases).length} variables</li>`).join("")}</ul>
        </div></div>
        <div class="card border-secondary-subtle"><div class="card-body">
          <h3 class="h6 text-uppercase text-secondary">SLURM</h3>
          <p class="mb-0">${state.slurm.enabled ? `Perlmutter CPU job, ${state.slurm.nodes} node(s), ${state.slurm.jobsPerNode} conversion(s)/node, ${Math.floor(128 / state.slurm.jobsPerNode)} CPU(s)/conversion` : "Disabled"}</p>
        </div></div>
        <div class="card border-secondary-subtle"><div class="card-body">
          <h3 class="h6 text-uppercase text-secondary">Open Data transfer</h3>
          <p class="mb-0">${state.slurm.openDataRelease}/${state.slurm.openDataDataset} (${state.slurm.openDataSkim}) to ${state.slurm.openDataDownloadDir}. ${state.slurm.openDataPreview ? `${formatBytes(state.slurm.openDataPreview.bytes)} estimated.` : "Preview not run."}</p>
        </div></div>`;
    }

    document.querySelectorAll("input[name='inputFormat']").forEach((input) => {
      input.addEventListener("change", () => {
        state.inputFormat = selectedInputFormat();
        ensureDependencies();
        renderObjects();
        renderVariables();
        updateGeneratedScript();
      });
    });

    document.getElementById("selectRecommended").addEventListener("click", () => {
      state.selectedObjects = new Set(Object.keys(OBJECTS).filter((key) => OBJECTS[key].recommended && isObjectAvailable(key)));
      ensureDependencies();
      renderObjects();
      renderVariables();
      updateGeneratedScript();
    });

    document.getElementById("selectAll").addEventListener("click", () => {
      state.selectedObjects = new Set(Object.keys(OBJECTS).filter(isObjectAvailable));
      ensureDependencies();
      renderObjects();
      renderVariables();
      updateGeneratedScript();
    });

    document.getElementById("selectNone").addEventListener("click", () => {
      state.selectedObjects = new Set(["Event"]);
      renderObjects();
      renderVariables();
      updateGeneratedScript();
    });

    document.getElementById("restoreDefaults").addEventListener("click", () => {
      Object.entries(OBJECTS).forEach(([key, object]) => {
        if (state.selectedObjects.has(key)) state.selectedVariables[key] = new Set(Object.keys(object.aliases));
      });
      renderVariables();
      updateGeneratedScript();
    });

    document.querySelectorAll(".slurm-input, #enableSlurm").forEach((input) => {
      input.addEventListener("input", updateGeneratedScript);
      input.addEventListener("change", updateGeneratedScript);
    });

    document.getElementById("previewOpenData").addEventListener("click", lookupOpenDataPreview);

    document.getElementById("prevStep").addEventListener("click", () => setStep(state.step - 1));
    document.getElementById("nextStep").addEventListener("click", () => setStep(state.step === 3 ? 3 : state.step + 1));
    document.querySelectorAll("[data-step-target]").forEach((button) => {
      button.addEventListener("click", () => setStep(Number(button.dataset.stepTarget)));
    });

    function tarString(value, length) {
      const bytes = new TextEncoder().encode(String(value));
      const output = new Uint8Array(length);
      output.set(bytes.slice(0, length));
      return output;
    }

    function tarOctal(value, length) {
      const text = value.toString(8).padStart(length - 1, "0") + "\0";
      return tarString(text, length);
    }

    function createTarArchive(files) {
      const encoder = new TextEncoder();
      const chunks = [];
      files.forEach((file) => {
        const data = encoder.encode(file.content);
        const header = new Uint8Array(512);
        const mode = file.mode ?? 0o644;
        header.set(tarString(file.name, 100), 0);
        header.set(tarOctal(mode, 8), 100);
        header.set(tarOctal(0, 8), 108);
        header.set(tarOctal(0, 8), 116);
        header.set(tarOctal(data.length, 12), 124);
        header.set(tarOctal(Math.floor(Date.now() / 1000), 12), 136);
        header.fill(32, 148, 156);
        header[156] = "0".charCodeAt(0);
        header.set(tarString("ustar", 6), 257);
        header.set(tarString("00", 2), 263);
        let checksum = 0;
        header.forEach((byte) => { checksum += byte; });
        header.set(tarOctal(checksum, 8), 148);
        chunks.push(header, data);
        const padding = (512 - (data.length % 512)) % 512;
        if (padding) chunks.push(new Uint8Array(padding));
      });
      chunks.push(new Uint8Array(1024));
      return new Blob(chunks, { type: "application/x-tar" });
    }

    function bundleReadme() {
      const pythonName = `ntuple-maker-${state.inputFormat.toLowerCase()}.py`;
      const slurmSection = state.slurm.enabled ? `
Perlmutter run
--------------
1. Copy this bundle to Perlmutter and extract it:
   tar -xf pcdf-ntuple-bundle.tar
   The Python, DTN transfer, and SLURM scripts are marked executable.
2. From a Perlmutter data transfer node, download the Open Data files to
   scratch and write the input manifest:
   ./download-atlas-opendata.sh
3. Return to a login node and edit submit-pcdf-ntuple.slurm if needed:
   account, manifest, output base, nodes, and conversions per node. The CPUs
   per conversion are derived from the fixed 128 CPU cores available on each
   Perlmutter CPU node.
4. Submit:
   sbatch submit-pcdf-ntuple.slurm
5. Monitor:
   squeue -u $USER
` : `
Perlmutter run
--------------
SLURM generation was disabled in the wizard, so this bundle contains the
Python converter, DTN transfer helper, and this README. Re-enable SLURM in the
wizard if you want a Perlmutter submission wrapper.
`;
      return applyTemplate(requireTemplate("readme"), {
        PYTHON_NAME: pythonName,
        TRANSFER_FILE_LINE: "- download-atlas-opendata.sh: executable DTN-only Open Data download helper.\n",
        SLURM_FILE_LINE: state.slurm.enabled
          ? "- submit-pcdf-ntuple.slurm: executable NERSC Perlmutter CPU/SLURM wrapper.\n"
          : "",
        SLURM_SECTION: slurmSection,
      });
    }

    function downloadBlob(blob, filename) {
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      link.click();
      URL.revokeObjectURL(url);
    }

    document.getElementById("downloadScript").addEventListener("click", () => {
      const blob = new Blob([scriptOutput.value], { type: "text/x-python" });
      downloadBlob(blob, `ntuple-maker-${state.inputFormat.toLowerCase()}.py`);
    });

    document.getElementById("downloadTransferScript").addEventListener("click", () => {
      const blob = new Blob([transferScriptOutput.value], { type: "text/x-shellscript" });
      downloadBlob(blob, "download-atlas-opendata.sh");
    });

    document.getElementById("downloadSlurmScript").addEventListener("click", () => {
      const blob = new Blob([slurmScriptOutput.value], { type: "text/x-shellscript" });
      downloadBlob(blob, "submit-pcdf-ntuple.slurm");
    });

    document.getElementById("downloadBundle").addEventListener("click", () => {
      const pythonName = `ntuple-maker-${state.inputFormat.toLowerCase()}.py`;
      const files = [
        { name: pythonName, content: scriptOutput.value, mode: 0o755 },
        { name: "download-atlas-opendata.sh", content: transferScriptOutput.value, mode: 0o755 },
      ];
      if (state.slurm.enabled) {
        files.push({
          name: "submit-pcdf-ntuple.slurm",
          content: slurmScriptOutput.value,
          mode: 0o755,
        });
      }
      files.push({ name: "README_SUBMIT.md", content: bundleReadme() });
      downloadBlob(createTarArchive(files), "pcdf-ntuple-bundle.tar");
    });


    function initWizard() {
      try {
        loadTemplates();
        ensureDependencies();
        renderObjects();
        renderVariables();
        updateGeneratedScript();
        setStep(0);
      } catch (error) {
        const message = `Template loading failed: ${error.message}`;
        scriptHighlight.textContent = message;
        slurmScriptHighlight.textContent = message;
        console.error(error);
      }
    }

    initWizard();
