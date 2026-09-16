    let OBJECTS = {};

    const OBJECT_CONFIG_URL = "ntuple-wizard.objects.json";


    const state = {
      step: 0,
      inputFormat: "JETM16",
      sampleType: "MC",
      activeVariableObject: "Event",
      selectedObjects: new Set(),
      objectSelectionsByFormat: {},
      selectedVariables: {},
      slurm: {
        enabled: true,
        scheduler: "slurm",
        account: "",
        qos: "regular",
        nodes: 1,
        time: "00:30:00",
        pythonPath: generatedPythonName("JETM16"),
        inputManifest: "./pcdf-inputs.txt",
        outputBase: "./output",
        condorCpus: 1,
        condorMemory: 4096,
        condorDisk: 4096,
        condorRequirements: ""
      }
    };

    const objectList = document.getElementById("objectList");
    const variableAccordion = document.getElementById("variableAccordion");
    const scriptOutput = document.getElementById("scriptOutput");
    const scriptHighlight = document.getElementById("scriptHighlight").querySelector("code");
    const slurmScriptOutput = document.getElementById("slurmScriptOutput");
    const slurmScriptHighlight = document.getElementById("slurmScriptHighlight").querySelector("code");
    const summary = document.getElementById("summary");
    const wizardStatus = document.getElementById("wizardStatus");

    const TEMPLATE_SOURCES = {
      python: {
        id: "template-python",
        url: "templates/ntuple-maker.template.py",
      },
      slurm: {
        id: "template-slurm",
        url: "templates/submit-pcdf-ntuple.template.slurm",
      },
      condor: {
        id: "template-condor",
        url: "templates/submit-pcdf-ntuple.template.condor",
      },
      condorJob: {
        id: "template-condor-job",
        url: "templates/run-pcdf-condor-job.template.sh",
      },
      readme: {
        id: "template-readme",
        url: "templates/README_SUBMIT.template.md",
      },
      manifest: {
        id: "template-manifest",
        url: "templates/make-manifest.template.py",
      },
      workflowShell: {
        id: "template-workflow-shell",
        url: "templates/run-pcdf.template.sh",
      },
      workflowPython: {
        id: "template-workflow-python",
        url: "templates/run-pcdf.template.py",
      },
    };

    const templates = {};
    let generationReady = false;


    function announce(message) {
      wizardStatus.textContent = "";
      window.requestAnimationFrame(() => {
        wizardStatus.textContent = message;
      });
    }


    function initAppearance() {
      const toggle = document.getElementById("textureToggle");
      const storageKey = "pcdf-material-textures";
      let enabled = true;

      try {
        const saved = window.localStorage.getItem(storageKey);
        if (saved !== null) enabled = saved === "on";
      } catch (_error) {
        // The preference is optional; the page still works if storage is unavailable.
      }

      const applyPreference = (useTextures) => {
        document.body.classList.toggle("textures-on", useTextures);
        toggle.checked = useTextures;
      };

      applyPreference(enabled);
      toggle.addEventListener("change", () => {
        applyPreference(toggle.checked);
        try {
          window.localStorage.setItem(storageKey, toggle.checked ? "on" : "off");
        } catch (_error) {
          // Keep the setting for this page view when storage is unavailable.
        }
      });
    }


    function initTermHelp() {
      const placeTooltip = (wrapper) => {
        const termRect = wrapper.querySelector(".term-label").getBoundingClientRect();
        const tooltip = wrapper.querySelector(".term-tooltip");
        const tooltipRect = tooltip.getBoundingClientRect();
        const margin = 8;
        const viewportWidth = document.documentElement.clientWidth;
        const viewportHeight = document.documentElement.clientHeight;
        const left = Math.max(margin, Math.min(termRect.left, viewportWidth - tooltipRect.width - margin));
        const below = termRect.bottom - 2;
        const above = termRect.top - tooltipRect.height + 2;
        const top = below + tooltipRect.height <= viewportHeight - margin ? below : Math.max(margin, above);
        tooltip.style.left = `${left}px`;
        tooltip.style.top = `${top}px`;
      };
      const closeTooltip = (wrapper, dismissed = false) => {
        wrapper.classList.toggle("tooltip-dismissed", dismissed);
      };

      document.querySelectorAll(".term-with-help").forEach((wrapper) => {
        wrapper.addEventListener("pointerenter", () => placeTooltip(wrapper));
        wrapper.addEventListener("mouseleave", () => closeTooltip(wrapper));
      });

      document.addEventListener("keydown", (event) => {
        if (event.key !== "Escape") return;
        document.querySelectorAll(".term-with-help").forEach((wrapper) => closeTooltip(wrapper, true));
      });
    }


    function initKeyboardShortcuts() {
      const glossary = document.getElementById("glossaryModal");
      const glossaryOpen = document.getElementById("glossaryOpen");
      const glossaryTitle = document.getElementById("glossaryTitle");
      const previous = document.getElementById("prevStep");
      const next = document.getElementById("nextStep");

      const openGlossary = () => {
        if (glossary.open) return;
        glossary.showModal();
        document.body.classList.add("modal-open");
        glossaryTitle.focus();
      };
      const closeGlossary = () => {
        if (glossary.open) glossary.close();
      };

      glossaryOpen.addEventListener("click", openGlossary);
      glossary.querySelectorAll("[data-glossary-close]").forEach((button) => {
        button.addEventListener("click", closeGlossary);
      });
      glossary.addEventListener("click", (event) => {
        if (event.target === glossary) closeGlossary();
      });
      glossary.addEventListener("close", () => {
        document.body.classList.remove("modal-open");
        glossaryOpen.focus();
      });

      document.addEventListener("keydown", (event) => {
        if (glossary.open && event.key === "Tab") {
          const controls = [...glossary.querySelectorAll("button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])")]
            .filter((control) => !control.hidden);
          if (!controls.length) return;
          const current = controls.indexOf(document.activeElement);
          const next = current < 0
            ? (event.shiftKey ? controls.length - 1 : 0)
            : (current + (event.shiftKey ? -1 : 1) + controls.length) % controls.length;
          event.preventDefault();
          controls[next].focus();
          return;
        }
        if (event.altKey || event.shiftKey || event.ctrlKey || event.metaKey || event.repeat) return;
        if (event.key === "F2") {
          event.preventDefault();
          if (glossary.open) closeGlossary();
          else openGlossary();
        } else if (event.key === "F8" && !glossary.open) {
          event.preventDefault();
          if (!previous.disabled) previous.click();
        } else if (event.key === "F9" && !glossary.open) {
          event.preventDefault();
          if (!next.disabled && !next.hidden) next.click();
        }
      });
    }


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
        if (element) {
          templates[name] = element.textContent.trimStart();
          return;
        }
        try {
          templates[name] = (await fetchText(source.url)).trimStart();
        } catch (error) {
          if (window.location.pathname === "/" && source.url.startsWith("templates/")) {
            templates[name] = (await fetchText(`ATLAS/${source.url}`)).trimStart();
            return;
          }
          throw error;
        }
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
      return `./code/ntuple-maker-${format.toLowerCase()}.py`;
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
      state.slurm.scheduler = fieldValue("scheduler") || "slurm";
      state.slurm.account = fieldValue("slurmAccount");
      state.slurm.qos = fieldValue("slurmQos") || "regular";
      state.slurm.nodes = numericFieldValue("slurmNodes", 1);
      state.slurm.time = fieldValue("slurmTime") || "00:30:00";
      state.slurm.pythonPath = fieldValue("slurmPythonPath") || generatedPythonName();
      state.slurm.inputManifest = fieldValue("slurmInputManifest") || "./pcdf-inputs.txt";
      state.slurm.outputBase = fieldValue("slurmOutputBase") || "./output";
      state.slurm.condorCpus = numericFieldValue("condorCpus", 1);
      state.slurm.condorMemory = numericFieldValue("condorMemory", 4096);
      state.slurm.condorDisk = numericFieldValue("condorDisk", 4096);
      state.slurm.condorRequirements = fieldValue("condorRequirements");
    }

    function selectedInputFormat() {
      return document.querySelector("input[name='inputFormat']:checked").value;
    }

    function selectedSampleType() {
      return document.querySelector("input[name='sampleType']:checked").value;
    }

    function rememberObjectSelection(format) {
      state.objectSelectionsByFormat[format] = new Set(state.selectedObjects);
    }

    function restoreObjectSelection(format) {
      const saved = state.objectSelectionsByFormat[format];
      if (saved) state.selectedObjects = new Set(saved);
    }

    function variableIsAvailable(key, name) {
      return !(state.sampleType === "DATA" && (OBJECTS[key].mcOnlyVariables || []).includes(name));
    }

    function availableVariableEntries(key) {
      return Object.entries(OBJECTS[key].aliases).filter(([name]) => variableIsAvailable(key, name));
    }

    function estimatedObjectBytesPerEvent(key) {
      const estimate = OBJECTS[key].sizeEstimate;
      if (!estimate || !isObjectAvailable(key)) return 0;
      return Array.from(state.selectedVariables[key] || []).reduce((total, name) => {
        if (!variableIsAvailable(key, name)) return total;
        return total + (estimate.variables[name] || 0);
      }, estimate.baseBytesPerEvent);
    }

    function estimatedTotalBytesPerEvent() {
      return Array.from(state.selectedObjects).reduce((total, key) => {
        return total + estimatedObjectBytesPerEvent(key);
      }, 0);
    }

    function formatBytesPerEvent(bytes) {
      if (bytes === 0) return "0 B/event";
      if (bytes >= 1000) return `${(bytes / 1000).toPrecision(2)} kB/event`;
      if (bytes >= 100) return `${Math.round(bytes / 10) * 10} B/event`;
      if (bytes >= 10) return `${Math.round(bytes)} B/event`;
      return `${bytes.toPrecision(2)} B/event`;
    }

    function sizeEstimateClass(bytes) {
      if (bytes >= 1000) return "size-cost-high";
      if (bytes >= 100) return "size-cost-medium";
      return "size-cost-low";
    }

    function updateSizeBadge(output, bytes) {
      output.textContent = formatBytesPerEvent(bytes);
      output.classList.remove("size-cost-low", "size-cost-medium", "size-cost-high");
      output.classList.add(sizeEstimateClass(bytes));
    }

    function updateSizeEstimates() {
      const total = formatBytesPerEvent(estimatedTotalBytesPerEvent());
      ["objectSizeEstimate", "variableSizeEstimate"].forEach((id) => {
        const output = document.getElementById(id);
        if (output) output.textContent = total;
      });
      Object.keys(OBJECTS).forEach((key) => {
        const output = document.getElementById(`obj-size-${key}`);
        if (output) updateSizeBadge(output, estimatedObjectBytesPerEvent(key));
      });
      const activeOutput = document.getElementById("activeObjectSizeEstimate");
      if (activeOutput && state.activeVariableObject) {
        updateSizeBadge(activeOutput, estimatedObjectBytesPerEvent(state.activeVariableObject));
      }
    }

    function isObjectAvailable(key) {
      return !(OBJECTS[key].requiresJetm16 && state.inputFormat === "PHYSLITE");
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
      const dependents = key === "Event"
        ? []
        : dependentObjectsFor(key).filter((dependent) => state.selectedObjects.has(dependent));
      const dependencies = dependenciesFor(key).filter((dependency) => dependency !== "Event");
      const badges = key === "Event"
        ? ['<span class="badge text-bg-info">Always included</span>']
        : [];
      if (dependencies.length) {
        badges.push(`<span class="badge text-bg-info">Requires ${dependencies.length === 1 ? OBJECTS[dependencies[0]].title : `${dependencies.length} other objects`}</span>`);
      }
      if (dependents.length) {
        badges.push(`<span class="badge text-bg-warning">Used by ${dependents.length} selected object${dependents.length === 1 ? "" : "s"}</span>`);
      }
      return badges.join("");
    }

    function renderObjects() {
      objectList.innerHTML = Object.entries(OBJECTS).map(([key, object]) => {
        const unavailable = !isObjectAvailable(key);
        const checked = state.selectedObjects.has(key) && !unavailable;
        const statusBadges = [
          dependencyBadges(key),
          unavailable ? '<span class="badge text-bg-warning">Not available for PHYSLITE</span>' : "",
          state.sampleType === "DATA" && (object.mcOnlyVariables || []).length ? '<span class="badge text-bg-info">Simulation-only labels omitted</span>' : "",
        ].filter(Boolean).join("");
        const descriptionIds = [`obj-desc-${key}`, `obj-meta-${key}`];
        if (statusBadges) descriptionIds.push(`obj-status-${key}`);
        return `
          <div class="col-md-6 col-xl-4">
            <label class="card object-card h-100 border-secondary-subtle ${unavailable ? "opacity-50" : ""}" for="obj-${key}">
              <div class="card-body">
                <div class="object-card-heading">
                  <div class="form-check form-switch mb-0">
                    <input class="form-check-input object-toggle" type="checkbox" value="${key}" id="obj-${key}" aria-labelledby="obj-label-${key}" aria-describedby="${descriptionIds.join(" ")}" ${checked ? "checked" : ""} ${unavailable || key === "Event" ? "disabled" : ""}>
                    <span class="form-check-label fw-semibold" id="obj-label-${key}">${object.title}</span>
                  </div>
                </div>
                <p class="small text-secondary mb-2" id="obj-desc-${key}">${object.description}</p>
                <div class="object-card-footer">
                  ${statusBadges ? `<div class="object-status" id="obj-status-${key}">${statusBadges}</div>` : ""}
                  <div class="object-meta" id="obj-meta-${key}">
                    <span class="badge text-bg-secondary object-variable-count">${availableVariableEntries(key).length} ${availableVariableEntries(key).length === 1 ? "variable" : "variables"}</span>
                    ${unavailable ? "" : `<span class="badge object-size-badge ${sizeEstimateClass(estimatedObjectBytesPerEvent(key))}" id="obj-size-${key}" title="Estimated Parquet size for this table">${formatBytesPerEvent(estimatedObjectBytesPerEvent(key))}</span>`}
                  </div>
                </div>
              </div>
            </label>
          </div>`;
      }).join("");
      updateSizeEstimates();

      objectList.querySelectorAll(".object-toggle").forEach((input) => {
        input.addEventListener("change", () => {
          const objectTitle = OBJECTS[input.value].title;
          const previouslySelected = new Set(state.selectedObjects);
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
          const relatedChanges = input.checked
            ? Array.from(state.selectedObjects).filter((key) => key !== input.value && !previouslySelected.has(key))
            : Array.from(previouslySelected).filter((key) => key !== input.value && !state.selectedObjects.has(key));
          const relatedTitles = relatedChanges.map((key) => OBJECTS[key].title).join(", ");
          announce(input.checked
            ? `${objectTitle} selected.${relatedTitles ? ` Also selected: ${relatedTitles}.` : ""}`
            : `${objectTitle} turned off.${relatedTitles ? ` Also turned off: ${relatedTitles}.` : ""}`);
          renderObjects();
          renderVariables();
          updateGeneratedScript();
          document.getElementById(`obj-${input.value}`)?.focus();
        });
      });
    }

    function renderVariables() {
      const selected = Object.keys(OBJECTS).filter((key) => state.selectedObjects.has(key) && isObjectAvailable(key));
      if (!selected.includes(state.activeVariableObject)) {
        state.activeVariableObject = selected[0];
      }
      if (!selected.length) {
        variableAccordion.innerHTML = '<div class="alert alert-warning">Select at least one output object before choosing variables.</div>';
        return;
      }

      const activeKey = state.activeVariableObject;
      const activeObject = OBJECTS[activeKey];
      const variables = Object.entries(activeObject.aliases).map(([name, branch]) => {
          const branchText = Array.isArray(branch) ? branch.join(" / ") : branch;
          const required = variableIsRequired(activeKey, name);
          const available = variableIsAvailable(activeKey, name);
          if (required && available) state.selectedVariables[activeKey].add(name);
          const checked = available && state.selectedVariables[activeKey].has(name);
          const detailIds = [`var-branch-${activeKey}-${name}`];
          if (required && available) detailIds.push(`var-required-${activeKey}-${name}`);
          if (!available) detailIds.push(`var-unavailable-${activeKey}-${name}`);
          return `
            <div class="form-check mb-2 ${available ? "" : "opacity-50"}">
              <input class="form-check-input variable-toggle" type="checkbox" value="${name}" data-object="${activeKey}" id="var-${activeKey}-${name}" aria-labelledby="var-label-${activeKey}-${name}" aria-describedby="${detailIds.join(" ")}" ${checked ? "checked" : ""} ${required || !available ? "disabled" : ""}>
              <label class="form-check-label" for="var-${activeKey}-${name}">
                <code class="variable-name" id="var-label-${activeKey}-${name}">${name}</code>
                ${required && available ? `<span class="badge text-bg-warning ms-1" id="var-required-${activeKey}-${name}">Required vector component</span>` : ""}
                ${!available ? `<span class="badge text-bg-info ms-1" id="var-unavailable-${activeKey}-${name}">Not written for collision data</span>` : ""}
                <span class="d-block small text-secondary" id="var-branch-${activeKey}-${name}">${branchText}</span>
              </label>
            </div>`;
      }).join("");
      const options = selected.map((key) =>
        `<option value="${key}" ${key === activeKey ? "selected" : ""}>${OBJECTS[key].title}</option>`
      ).join("");
      const tabs = selected.map((key) => `
        <button class="variable-tab" id="variable-tab-${key}" type="button" role="tab" aria-selected="${key === activeKey}" aria-controls="variable-panel" tabindex="${key === activeKey ? "0" : "-1"}" data-object="${key}">
          ${OBJECTS[key].title}
        </button>`).join("");

      variableAccordion.innerHTML = `
        <div class="variable-tabs-layout">
          <div class="variable-tabs-controls">
            <label class="form-label variable-object-select-label" for="variableObjectSelect">Object</label>
            <select class="form-select variable-object-select" id="variableObjectSelect">${options}</select>
            <div class="variable-tab-list" role="tablist" aria-label="Output objects" aria-orientation="vertical">${tabs}</div>
          </div>
          <section class="variable-panel" id="variable-panel" role="tabpanel" tabindex="0" aria-labelledby="variable-tab-${activeKey}">
            <h3 class="h5">${activeObject.title} variables <span class="badge ${sizeEstimateClass(estimatedObjectBytesPerEvent(activeKey))}" id="activeObjectSizeEstimate">${formatBytesPerEvent(estimatedObjectBytesPerEvent(activeKey))}</span></h3>
            <div class="variable-grid">${variables}</div>
          </section>
        </div>`;

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
          updateSizeEstimates();
          updateGeneratedScript();
        });
      });

      const activateObject = (key, focusSelector) => {
        state.activeVariableObject = key;
        renderVariables();
        window.requestAnimationFrame(() => document.querySelector(focusSelector)?.focus());
      };

      variableAccordion.querySelector(".variable-object-select").addEventListener("change", (event) => {
        activateObject(event.target.value, ".variable-object-select");
        announce(`Showing ${OBJECTS[event.target.value].title} variables.`);
      });

      const tabButtons = Array.from(variableAccordion.querySelectorAll(".variable-tab"));
      tabButtons.forEach((button, index) => {
        button.addEventListener("click", () => {
          activateObject(button.dataset.object, `#variable-tab-${button.dataset.object}`);
          announce(`Showing ${OBJECTS[button.dataset.object].title} variables.`);
        });
        button.addEventListener("keydown", (event) => {
          let nextIndex;
          if (["ArrowDown", "ArrowRight"].includes(event.key)) nextIndex = (index + 1) % tabButtons.length;
          if (["ArrowUp", "ArrowLeft"].includes(event.key)) nextIndex = (index - 1 + tabButtons.length) % tabButtons.length;
          if (event.key === "Home") nextIndex = 0;
          if (event.key === "End") nextIndex = tabButtons.length - 1;
          if (nextIndex === undefined) return;
          event.preventDefault();
          const nextKey = tabButtons[nextIndex].dataset.object;
          activateObject(nextKey, `#variable-tab-${nextKey}`);
          announce(`Showing ${OBJECTS[nextKey].title} variables.`);
        });
      });
      updateSizeEstimates();
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

    function setStep(step, moveFocus = true) {
      state.step = Math.max(0, Math.min(4, step));
      document.querySelectorAll(".wizard-step").forEach((section) => {
        const active = Number(section.dataset.step) === state.step;
        section.classList.toggle("d-none", !active);
        section.hidden = !active;
      });
      document.querySelectorAll("[data-step-target]").forEach((button) => {
        const active = Number(button.dataset.stepTarget) === state.step;
        button.classList.toggle("active", active);
        if (active) button.setAttribute("aria-current", "step");
        else button.removeAttribute("aria-current");
      });
      document.getElementById("prevStep").disabled = state.step === 0;
      const nextButton = document.getElementById("nextStep");
      nextButton.hidden = state.step === 4;
      nextButton.textContent = state.step === 3 ? "Review" : "Next";
      const activeSection = document.querySelector(`.wizard-step[data-step="${state.step}"]`);
      const heading = activeSection.querySelector("h2");
      if (moveFocus) heading.focus({ preventScroll: true });
    }

    function selectedVariables(key) {
      return Array.from(state.selectedVariables[key] || []).filter((name) => {
        return Object.hasOwn(OBJECTS[key].aliases, name) && variableIsAvailable(key, name);
      });
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
      return { inputFormat: state.inputFormat, sampleType: state.sampleType, objects };
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
      const formatNote = config.inputFormat === "PHYSLITE"
        ? "PHYSLITE does not contain the data needed for jet constituents, so that output is off."
        : "JETM16 contains the data needed for jet constituents.";
      const sampleNote = config.sampleType === "DATA"
        ? "For collision data, truth and flavor fields are skipped. Events include lumiBlock."
        : "Simulation input can include the truth and flavor fields you select.";
      const inputNote = `${formatNote} ${sampleNote}`;
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
        LOG_OUT: JSON.stringify("logs/pcdf-ntuple-%j.out"),
        LOG_ERR: JSON.stringify("logs/pcdf-ntuple-%j.err"),
      };
    }

    function buildSlurmScript() {
      const slurm = state.slurm;
      const accountLine = `#SBATCH --account=${slurm.account}`;
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

    function buildCondorSubmitFile() {
      const batch = state.slurm;
      return applyTemplate(requireTemplate("condor"), {
        PYTHON_PATH: JSON.stringify(batch.pythonPath),
        INPUT_MANIFEST: JSON.stringify(batch.inputManifest),
        OUTPUT_BASE: JSON.stringify(batch.outputBase),
        REQUEST_CPUS: batch.condorCpus,
        REQUEST_MEMORY_MB: batch.condorMemory,
        REQUEST_DISK_MB: batch.condorDisk,
        REQUIREMENTS_LINE: batch.condorRequirements
          ? `requirements = ${batch.condorRequirements}`
          : "",
      });
    }

    function batchFilename() {
      return state.slurm.scheduler === "condor"
        ? "submit-pcdf-ntuple.condor"
        : "submit-pcdf-ntuple.slurm";
    }

    function updateSchedulerControls() {
      const enabled = state.slurm.enabled;
      const condor = state.slurm.scheduler === "condor";
      document.querySelectorAll(".slurm-only").forEach((element) => {
        element.hidden = condor;
        element.querySelectorAll("input, select").forEach((control) => {
          control.disabled = !enabled || condor;
        });
      });
      document.querySelectorAll(".condor-only").forEach((element) => {
        element.hidden = !condor;
        element.querySelectorAll("input, select").forEach((control) => {
          control.disabled = !enabled || !condor;
        });
      });
      document.querySelectorAll(".slurm-input:not(#scheduler)").forEach((input) => {
        if (!input.closest(".slurm-only") && !input.closest(".condor-only")) {
          input.disabled = !enabled;
        }
      });
      document.getElementById("scheduler").disabled = !enabled;
    }

    function updateRunInstructions() {
      const instructions = document.getElementById("slurmRunInstructions");
      if (state.slurm.scheduler === "condor") {
        instructions.innerHTML = `
          <li>Extract the bundle on a filesystem shared by the HTCondor access point and execute nodes. Enter the <code>pcdf-ntuple</code> directory.</li>
          <li>Make sure <code>uv</code> is available on the execute nodes. They must also be able to read the input paths and write to the output directory.</li>
          <li>Run <code>./run-pcdf.sh</code>. The workflow creates the manifest, asks before submission, and follows the jobs until they finish. It does not transfer DAOD files.</li>`;
      } else {
        instructions.innerHTML = `
          <li>Copy the bundle to a Perlmutter login node, extract it, and enter the <code>pcdf-ntuple</code> directory.</li>
          <li>Run <code>./run-pcdf.sh</code>. The workflow finds the input files, writes the manifest, asks before submission, and follows the job until it finishes.</li>
          <li>You can stop monitoring without cancelling the job. Scheduler output and error messages are written under <code>logs/</code>.</li>`;
      }
    }

    function setDownloadButtonsEnabled(enabled) {
      document.getElementById("downloadScript").disabled = !enabled;
      document.getElementById("downloadBundle").disabled = !enabled;
      document.getElementById("downloadSlurmScript").disabled = !enabled || !state.slurm.enabled;
    }


    function updateGeneratedScript() {
      syncSlurmSettings();
      updateSchedulerControls();
      ensureDependencies();
      const config = selectedConfig();
      const generatedScript = buildScript();
      const slurmScript = state.slurm.scheduler === "condor" ? buildCondorSubmitFile() : buildSlurmScript();
      scriptOutput.value = generatedScript;
      scriptHighlight.innerHTML = highlightPython(generatedScript);
      slurmScriptOutput.value = slurmScript;
      slurmScriptHighlight.innerHTML = state.slurm.enabled ? highlightPython(slurmScript) : "Batch file generation is turned off.";
      document.getElementById("runInstructions").hidden = !state.slurm.enabled;
      updateRunInstructions();
      document.getElementById("slurmScriptHighlightHeading").textContent = state.slurm.scheduler === "condor"
        ? "Generated HTCondor submit file"
        : "Generated SLURM submission script";
      document.getElementById("downloadSlurmScript").innerHTML = `<i class="bi bi-download me-1" aria-hidden="true"></i>Download ${state.slurm.scheduler === "condor" ? "HTCondor file" : "SLURM script"}`;
      generationReady = true;
      setDownloadButtonsEnabled(true);
      const slurmSummary = !state.slurm.enabled
        ? "No batch submission file will be generated."
        : state.slurm.scheduler === "condor"
          ? `HTCondor queues one job per input file. Each job requests ${state.slurm.condorCpus} CPU core${state.slurm.condorCpus === 1 ? "" : "s"} and ${state.slurm.condorMemory} MiB of memory.`
          : `The SLURM job uses ${state.slurm.nodes} whole CPU node${state.slurm.nodes === 1 ? "" : "s"}. It runs one file conversion on each physical CPU core.`;
      const objectSummary = Object.keys(config.objects).map((key) => {
        const title = escapeHtml(OBJECTS[key].title);
        const variableCount = Object.keys(config.objects[key].aliases).length;
        return `<li>${title}: ${variableCount} ${variableCount === 1 ? "variable" : "variables"}</li>`;
      }).join("");
      const manifestSummary = state.slurm.enabled
        ? `The workflow writes input paths to ${escapeHtml(state.slurm.inputManifest)} before submission. Every path must be readable from the compute nodes.`
        : "You do not need a manifest when batch file generation is off.";
      summary.innerHTML = `
        <div class="card border-secondary-subtle"><div class="card-body">
          <h3 class="h6 text-uppercase text-secondary">Input</h3>
          <p class="mb-1 fw-semibold">${escapeHtml(config.inputFormat)} · ${escapeHtml(config.sampleType)}</p>
          <p class="mb-0 small">Estimated Parquet size: ${escapeHtml(formatBytesPerEvent(estimatedTotalBytesPerEvent()))}</p>
        </div></div>
        <div class="card border-secondary-subtle"><div class="card-body">
          <h3 class="h6 text-uppercase text-secondary">Objects</h3>
          <ul class="mb-0">${objectSummary}</ul>
        </div></div>
        <div class="card border-secondary-subtle"><div class="card-body">
          <h3 class="h6 text-uppercase text-secondary">Batch job</h3>
          <p class="mb-0">${escapeHtml(slurmSummary)}</p>
        </div></div>
        <div class="card border-secondary-subtle"><div class="card-body">
          <h3 class="h6 text-uppercase text-secondary">Input manifest</h3>
          <p class="mb-0">${manifestSummary}</p>
        </div></div>`;
    }

    document.querySelectorAll("input[name='inputFormat'], input[name='sampleType']").forEach((input) => {
      input.addEventListener("change", () => {
        const previousDefaultPython = generatedPythonName(state.inputFormat);
        const previousInputFormat = state.inputFormat;
        const nextInputFormat = selectedInputFormat();
        if (nextInputFormat !== previousInputFormat) {
          rememberObjectSelection(previousInputFormat);
          state.inputFormat = nextInputFormat;
          restoreObjectSelection(nextInputFormat);
        }
        state.sampleType = selectedSampleType();
        const pythonPathInput = document.getElementById("slurmPythonPath");
        if (state.inputFormat !== previousInputFormat &&
            (!pythonPathInput.value.trim() || pythonPathInput.value.trim() === previousDefaultPython)) {
          pythonPathInput.value = generatedPythonName();
        }
        ensureDependencies();
        renderObjects();
        renderVariables();
        updateGeneratedScript();
        announce(`Input set to ${state.inputFormat}, ${state.sampleType === "MC" ? "simulation" : "collision data"}.`);
      });
    });

    document.getElementById("selectRecommended").addEventListener("click", () => {
      state.selectedObjects = new Set(Object.keys(OBJECTS).filter((key) => OBJECTS[key].recommended && isObjectAvailable(key)));
      ensureDependencies();
      renderObjects();
      renderVariables();
      updateGeneratedScript();
      announce("Recommended output objects selected.");
    });

    document.getElementById("selectAll").addEventListener("click", () => {
      state.selectedObjects = new Set(Object.keys(OBJECTS).filter(isObjectAvailable));
      ensureDependencies();
      renderObjects();
      renderVariables();
      updateGeneratedScript();
      announce("All available output objects selected.");
    });

    document.getElementById("restoreDefaults").addEventListener("click", () => {
      Object.entries(OBJECTS).forEach(([key, object]) => {
        if (state.selectedObjects.has(key)) state.selectedVariables[key] = new Set(availableVariableEntries(key).map(([name]) => name));
      });
      renderVariables();
      updateGeneratedScript();
      announce("All available variables were restored for the objects you selected.");
    });

    document.querySelectorAll(".slurm-input, #enableSlurm").forEach((input) => {
      input.addEventListener("input", updateGeneratedScript);
      input.addEventListener("change", updateGeneratedScript);
    });

    document.getElementById("enableSlurm").addEventListener("change", (event) => {
      announce(event.target.checked
        ? "Batch file generation is on."
        : "Batch file generation is off. Scheduler settings are no longer needed.");
    });

    document.querySelectorAll(".slurm-input").forEach((input) => {
      input.addEventListener("input", () => {
        if (input.checkValidity()) setControlValidity(input, true);
      });
    });

    function setControlValidity(control, valid) {
      const errorId = control.dataset.errorId;
      const descriptionIds = new Set((control.getAttribute("aria-describedby") || "").split(/\s+/).filter(Boolean));
      if (errorId) {
        if (valid) descriptionIds.delete(errorId);
        else descriptionIds.add(errorId);
      }
      if (descriptionIds.size) control.setAttribute("aria-describedby", Array.from(descriptionIds).join(" "));
      else control.removeAttribute("aria-describedby");
      if (valid) control.removeAttribute("aria-invalid");
      else control.setAttribute("aria-invalid", "true");
    }

    function formIsValid() {
      const form = document.getElementById("wizardForm");
      form.classList.add("was-validated");
      const controls = Array.from(form.querySelectorAll("input, select, textarea"));
      controls.forEach((control) => {
        setControlValidity(control, control.disabled || control.checkValidity());
      });
      if (form.checkValidity()) return true;

      const firstInvalid = form.querySelector(":invalid");
      if (!firstInvalid) {
        announce("Check the form before you continue.");
        return false;
      }
      const invalidStep = firstInvalid.closest(".wizard-step");
      if (invalidStep) setStep(Number(invalidStep.dataset.step), false);
      const hiddenGroup = firstInvalid.closest("details");
      if (hiddenGroup) hiddenGroup.open = true;
      const error = document.getElementById(firstInvalid.dataset.errorId);
      window.requestAnimationFrame(() => firstInvalid.focus());
      announce(`Cannot continue. ${error ? error.textContent.trim() : firstInvalid.validationMessage}`);
      return false;
    }

    document.getElementById("prevStep").addEventListener("click", () => setStep(state.step - 1));
    document.getElementById("nextStep").addEventListener("click", () => {
      if (state.step === 3 && !formIsValid()) return;
      setStep(state.step + 1);
    });
    document.querySelectorAll("[data-step-target]").forEach((button) => {
      button.addEventListener("click", () => {
        const target = Number(button.dataset.stepTarget);
        if (target >= 4 && !formIsValid()) return;
        setStep(target);
      });
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
        const directory = file.type === "directory";
        const data = encoder.encode(directory ? "" : file.content);
        const header = new Uint8Array(512);
        const mode = file.mode ?? 0o644;
        header.set(tarString(file.name, 100), 0);
        header.set(tarOctal(mode, 8), 100);
        header.set(tarOctal(0, 8), 108);
        header.set(tarOctal(0, 8), 116);
        header.set(tarOctal(data.length, 12), 124);
        header.set(tarOctal(Math.floor(Date.now() / 1000), 12), 136);
        header.fill(32, 148, 156);
        header[156] = (directory ? "5" : "0").charCodeAt(0);
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
      const pythonName = generatedPythonName().split("/").pop();
      let batchFileLine = "";
      let workflowFileLine = "";
      let batchSection = `
Batch run
---------
This bundle has only the converter, manifest helper, and README. Turn on batch
file generation in the wizard to include a scheduler submission file.
`;
      if (state.slurm.enabled && state.slurm.scheduler === "condor") {
        batchFileLine = "- code/submit-pcdf-ntuple.condor describes one HTCondor job for each manifest entry.\n- code/run-pcdf-condor-job.sh runs one file conversion on an execute node.\n";
        workflowFileLine = "- run-pcdf.sh starts the interactive manifest, submission, and monitoring workflow.\n";
        batchSection = `
HTCondor run
------------
1. Extract the bundle on a filesystem shared by the access point and execute
   nodes:
   tar -xf pcdf-ntuple-bundle.tar
   cd pcdf-ntuple
2. Make sure uv is available on the execute nodes. The input paths and output
   directory must be visible at the same paths on every node. This workflow
   does not transfer DAOD files through HTCondor.
3. Run ./run-pcdf.sh. It creates the manifest, asks before submission, and
   follows the jobs until they finish.
4. To run each step yourself, use code/make-manifest.py, condor_submit
   code/submit-pcdf-ntuple.condor, and condor_q.
`;
      } else if (state.slurm.enabled) {
        batchFileLine = "- code/submit-pcdf-ntuple.slurm is the executable CPU job script for NERSC Perlmutter.\n";
        workflowFileLine = "- run-pcdf.sh starts the interactive manifest, submission, and monitoring workflow.\n";
        batchSection = `
Perlmutter run
--------------
1. Copy this bundle to Perlmutter and extract it:
   tar -xf pcdf-ntuple-bundle.tar
   cd pcdf-ntuple
2. Start the workflow from a login node:
   ./run-pcdf.sh
   It asks whether to scan a directory populated by \`rucio download\` or look
   up a \`scope:name\` dataset at \`NERSC_LOCALGROUPDISK\`. It then writes the
   manifest, asks before submission, and follows the job until it finishes.
3. You can stop monitoring with Ctrl+C without cancelling the job. Scheduler
   output and error messages are written under logs/.
4. To control each step yourself, use code/make-manifest.py, sbatch
   code/submit-pcdf-ntuple.slurm, and squeue -u $USER.
`;
      }
      return applyTemplate(requireTemplate("readme"), {
        PYTHON_NAME: pythonName,
        SLURM_FILE_LINE: batchFileLine,
        WORKFLOW_FILE_LINE: workflowFileLine,
        SLURM_SECTION: batchSection,
      });
    }

    function downloadBlob(blob, filename) {
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.append(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 0);
    }

    document.getElementById("downloadScript").addEventListener("click", () => {
      if (!generationReady || !scriptOutput.value || !formIsValid()) return;
      const blob = new Blob([scriptOutput.value], { type: "text/x-python" });
      downloadBlob(blob, generatedPythonName().split("/").pop());
      announce("Converter download started.");
    });

    document.getElementById("downloadSlurmScript").addEventListener("click", () => {
      if (!generationReady || !state.slurm.enabled || !slurmScriptOutput.value || !formIsValid()) return;
      const blob = new Blob([slurmScriptOutput.value], { type: "text/x-shellscript" });
      downloadBlob(blob, batchFilename());
      announce(`${state.slurm.scheduler === "condor" ? "HTCondor" : "SLURM"} file download started.`);
    });

    document.getElementById("downloadBundle").addEventListener("click", () => {
      if (!generationReady || !scriptOutput.value || !formIsValid()) return;
      try {
        const pythonName = generatedPythonName().split("/").pop();
        const root = "pcdf-ntuple";
        const files = [
          { name: `${root}/`, content: "", type: "directory", mode: 0o755 },
          { name: `${root}/code/`, content: "", type: "directory", mode: 0o755 },
          { name: `${root}/output/`, content: "", type: "directory", mode: 0o755 },
          { name: `${root}/logs/`, content: "", type: "directory", mode: 0o755 },
          { name: `${root}/code/${pythonName}`, content: scriptOutput.value, mode: 0o755 },
        ];
        if (state.slurm.enabled) {
          files.push({
            name: `${root}/code/${batchFilename()}`,
            content: slurmScriptOutput.value,
            mode: 0o755,
          });
          if (state.slurm.scheduler === "condor") {
            files.push({
              name: `${root}/code/run-pcdf-condor-job.sh`,
              content: requireTemplate("condorJob"),
              mode: 0o755,
            });
          }
          files.push({
            name: `${root}/run-pcdf.sh`,
            content: requireTemplate("workflowShell"),
            mode: 0o755,
          });
          files.push({
            name: `${root}/code/run-pcdf.py`,
            content: requireTemplate("workflowPython"),
            mode: 0o755,
          });
        }
        files.push({
          name: `${root}/code/make-manifest.py`,
          content: requireTemplate("manifest"),
          mode: 0o755,
        });
        files.push({ name: `${root}/README_SUBMIT.md`, content: bundleReadme() });
        downloadBlob(createTarArchive(files), "pcdf-ntuple-bundle.tar");
        announce("Bundle download started.");
      } catch (error) {
        console.error(error);
        announce(`Bundle download failed: ${error.message}`);
      }
    });


    async function initWizard() {
      initAppearance();
      initTermHelp();
      initKeyboardShortcuts();
      try {
        await loadObjectConfig();
        await loadTemplates();
        state.inputFormat = selectedInputFormat();
        state.sampleType = selectedSampleType();
        syncSlurmSettings();
        ensureDependencies();
        renderObjects();
        renderVariables();
        updateGeneratedScript();
        setStep(0, false);
      } catch (error) {
        generationReady = false;
        setDownloadButtonsEnabled(false);
        const message = `The wizard could not load the files it needs: ${error.message}`;
        scriptHighlight.textContent = message;
        slurmScriptHighlight.textContent = message;
        announce(message);
        console.error(error);
      }
    }

    setDownloadButtonsEnabled(false);
    initWizard();
