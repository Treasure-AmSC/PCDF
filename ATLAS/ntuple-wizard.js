    let OBJECTS = {};

    const OBJECT_CONFIG_URL = "ntuple-wizard.objects.json";


    const state = {
      step: 0,
      inputFormat: "TREASURE",
      selectedObjects: new Set(),
      selectedVariables: {},
      slurm: {
        enabled: true,
        account: "<NERSC_PROJECT>",
        qos: "regular",
        nodes: 1,
        time: "02:00:00",
        pythonPath: generatedPythonName("TREASURE"),
        inputManifest: "$SCRATCH/pcdf-inputs.txt",
        outputBase: "$SCRATCH/pcdf-output"
      }
    };

    const objectList = document.getElementById("objectList");
    const variableAccordion = document.getElementById("variableAccordion");
    const scriptOutput = document.getElementById("scriptOutput");
    const scriptHighlight = document.getElementById("scriptHighlight").querySelector("code");
    const slurmScriptOutput = document.getElementById("slurmScriptOutput");
    const slurmScriptHighlight = document.getElementById("slurmScriptHighlight").querySelector("code");
    const summary = document.getElementById("summary");

    const TEMPLATE_SOURCES = {
      python: {
        id: "template-python",
        url: "templates/ntuple-maker.template.py",
      },
      slurm: {
        id: "template-slurm",
        url: "templates/submit-pcdf-ntuple.template.slurm",
      },
      readme: {
        id: "template-readme",
        url: "templates/README_SUBMIT.template.md",
      },
    };

    const templates = {};
    let generationReady = false;


    async function fetchText(url) {
      const response = await fetch(url, { cache: "no-store" });
      if (!response.ok) throw new Error(`${url} returned HTTP ${response.status}`);
      return response.text();
    }

    async function loadObjectConfig() {
      const embedded = document.getElementById("object-config");
      const text = embedded ? embedded.textContent : await fetchText(OBJECT_CONFIG_URL);
      OBJECTS = JSON.parse(text);
      state.selectedObjects = new Set(
        Object.keys(OBJECTS).filter((key) => OBJECTS[key].recommended),
      );
      state.selectedVariables = Object.fromEntries(
        Object.entries(OBJECTS).map(([key, object]) => [
          key,
          new Set(Object.keys(object.aliases)),
        ]),
      );
    }

    async function loadTemplates() {
      await Promise.all(Object.entries(TEMPLATE_SOURCES).map(async ([name, source]) => {
        const element = document.getElementById(source.id);
        templates[name] = element
          ? element.textContent.trimStart()
          : (await fetchText(source.url)).trimStart();
      }));
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

    function generatedPythonName(format = state.inputFormat) {
      return `./ntuple-maker-${format.toLowerCase()}.py`;
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
      state.slurm.time = fieldValue("slurmTime") || "02:00:00";
      state.slurm.pythonPath = fieldValue("slurmPythonPath") || generatedPythonName();
      state.slurm.inputManifest = fieldValue("slurmInputManifest") || "$SCRATCH/pcdf-inputs.txt";
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
      state.step = Math.max(0, Math.min(5, step));
      document.querySelectorAll(".wizard-step").forEach((section) => {
        section.classList.toggle("d-none", Number(section.dataset.step) !== state.step);
      });
      document.querySelectorAll("[data-step-target]").forEach((button) => {
        button.classList.toggle("active", Number(button.dataset.stepTarget) === state.step);
      });
      document.getElementById("prevStep").disabled = state.step === 0;
      document.getElementById("nextStep").textContent = state.step === 5 ? "Regenerate" : "Next";
      if (state.step === 5) updateGeneratedScript();
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

    function commonBatchValues() {
      const slurm = state.slurm;
      return {
        PYTHON_PATH: JSON.stringify(slurm.pythonPath),
        INPUT_MANIFEST: JSON.stringify(slurm.inputManifest),
        OUTPUT_BASE: JSON.stringify(slurm.outputBase),
      };
    }

    function buildSlurmScript() {
      const slurm = state.slurm;
      const accountLine = slurm.account
        ? `#SBATCH --account=${slurm.account}`
        : "#SBATCH --account=<NERSC_PROJECT>";
      const perlmutterPhysicalCores = 128;
      const perlmutterLogicalCpus = 256;
      const converterCpusPerConversion = 1;
      return applyTemplate(requireTemplate("slurm"), {
        ...commonBatchValues(),
        ACCOUNT_LINE: accountLine,
        QOS: slurm.qos,
        NODES: slurm.nodes,
        CONVERTER_CPUS_PER_CONVERSION: converterCpusPerConversion,
        PERLMUTTER_PHYSICAL_CORES: perlmutterPhysicalCores,
        PERLMUTTER_LOGICAL_CPUS_PER_NODE: perlmutterLogicalCpus,
        TIME: slurm.time,
      });
    }

    function setDownloadButtonsEnabled(enabled) {
      document.getElementById("downloadScript").disabled = !enabled;
      document.getElementById("downloadBundle").disabled = !enabled;
      document.getElementById("downloadSlurmScript").disabled = !enabled || !state.slurm.enabled;
    }


    function updateGeneratedScript() {
      syncSlurmSettings();
      ensureDependencies();
      const config = selectedConfig();
      const generatedScript = buildScript();
      const slurmScript = buildSlurmScript();
      scriptOutput.value = generatedScript;
      scriptHighlight.innerHTML = highlightPython(generatedScript);
      slurmScriptOutput.value = slurmScript;
      slurmScriptHighlight.innerHTML = state.slurm.enabled ? highlightPython(slurmScript) : "SLURM wrapper disabled.";
      generationReady = true;
      setDownloadButtonsEnabled(true);
      const slurmSummary = state.slurm.enabled
        ? `Perlmutter CPU job, ${state.slurm.nodes} exclusive node(s); runtime core discovery fills physical cores with one conversion per core.`
        : "Disabled";
      const objectSummary = Object.keys(config.objects).map((key) => {
        const title = escapeHtml(OBJECTS[key].title);
        const variableCount = Object.keys(config.objects[key].aliases).length;
        return `<li>${title}: ${variableCount} variables</li>`;
      }).join("");
      const manifestSummary = `Use manifest ${escapeHtml(state.slurm.inputManifest)}; create it before submitting because the compute job does not download data.`;
      summary.innerHTML = `
        <div class="card border-secondary-subtle"><div class="card-body">
          <h3 class="h6 text-uppercase text-secondary">Input</h3>
          <p class="mb-0 fw-semibold">${escapeHtml(config.inputFormat)}</p>
        </div></div>
        <div class="card border-secondary-subtle"><div class="card-body">
          <h3 class="h6 text-uppercase text-secondary">Objects</h3>
          <ul class="mb-0">${objectSummary}</ul>
        </div></div>
        <div class="card border-secondary-subtle"><div class="card-body">
          <h3 class="h6 text-uppercase text-secondary">SLURM</h3>
          <p class="mb-0">${escapeHtml(slurmSummary)}</p>
        </div></div>
        <div class="card border-secondary-subtle"><div class="card-body">
          <h3 class="h6 text-uppercase text-secondary">Input manifest</h3>
          <p class="mb-0">${manifestSummary}</p>
        </div></div>`;
    }

    document.querySelectorAll("input[name='inputFormat']").forEach((input) => {
      input.addEventListener("change", () => {
        const previousDefaultPython = generatedPythonName(state.inputFormat);
        state.inputFormat = selectedInputFormat();
        const pythonPathInput = document.getElementById("slurmPythonPath");
        if (!pythonPathInput.value.trim() || pythonPathInput.value.trim() === previousDefaultPython) {
          pythonPathInput.value = generatedPythonName();
        }
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

    document.getElementById("prevStep").addEventListener("click", () => setStep(state.step - 1));
    document.getElementById("nextStep").addEventListener("click", () => setStep(state.step === 4 ? 4 : state.step + 1));
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
      const pythonName = generatedPythonName().replace(/^\.\//, "");
      const slurmSection = state.slurm.enabled ? `
Perlmutter run
--------------
1. Copy this bundle to Perlmutter and extract it:
   tar -xf pcdf-ntuple-bundle.tar
   The Python and SLURM scripts are marked executable.
2. Create the input manifest listed in submit-pcdf-ntuple.slurm. Do not download data on compute nodes.
3. Return to a login node and edit submit-pcdf-ntuple.slurm if needed:
   account, manifest, output base, and nodes. The output base is a single
   Hive-partitioned dataset root. The generated wrapper requests
   exclusive nodes, discovers physical cores at runtime, counts the manifest,
   and fills the available cores with one conversion per core.
4. Submit:
   sbatch submit-pcdf-ntuple.slurm
5. Monitor:
   squeue -u $USER
` : `
Perlmutter run
--------------
SLURM generation was disabled in the wizard, so this bundle contains the
Python converter and this README. Re-enable SLURM in the
wizard if you want a Perlmutter submission wrapper.
`;
      return applyTemplate(requireTemplate("readme"), {
        PYTHON_NAME: pythonName,
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
      if (!generationReady || !scriptOutput.value) return;
      const blob = new Blob([scriptOutput.value], { type: "text/x-python" });
      downloadBlob(blob, generatedPythonName().replace(/^\.\//, ""));
    });

    document.getElementById("downloadSlurmScript").addEventListener("click", () => {
      if (!generationReady || !state.slurm.enabled || !slurmScriptOutput.value) return;
      const blob = new Blob([slurmScriptOutput.value], { type: "text/x-shellscript" });
      downloadBlob(blob, "submit-pcdf-ntuple.slurm");
    });

    document.getElementById("downloadBundle").addEventListener("click", () => {
      if (!generationReady || !scriptOutput.value) return;
      const pythonName = generatedPythonName().replace(/^\.\//, "");
      const files = [
        { name: pythonName, content: scriptOutput.value, mode: 0o755 },
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


    async function initWizard() {
      try {
        await loadObjectConfig();
        await loadTemplates();
        ensureDependencies();
        renderObjects();
        renderVariables();
        updateGeneratedScript();
        setStep(0);
      } catch (error) {
        generationReady = false;
        setDownloadButtonsEnabled(false);
        const message = `Wizard resource loading failed: ${error.message}`;
        scriptHighlight.textContent = message;
        slurmScriptHighlight.textContent = message;
        console.error(error);
      }
    }

    setDownloadButtonsEnabled(false);
    initWizard();
