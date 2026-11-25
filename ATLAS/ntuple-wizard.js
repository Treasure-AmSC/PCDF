    let OBJECTS = {};


    const state = {
      step: 0,
      inputFormat: "JETMOD1",
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
        pythonPath: generatedPythonName("JETMOD1"),
        inputManifest: "./pcdf-inputs.txt",
        outputBase: "./output",
        condorCpus: 1,
        condorMemory: 2048,
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

    // The page embeds each template in a script element, so nothing is fetched.
    const TEMPLATE_IDS = {
      python: "template-python",
      slurm: "template-slurm",
      condor: "template-condor",
      condorJob: "template-condor-job",
      readme: "template-readme",
      manifest: "template-manifest",
      workflowShell: "template-workflow-shell",
      workflowPython: "template-workflow-python",
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
      const fixedContainingBlock = (element) => {
        for (let ancestor = element.parentElement; ancestor && ancestor !== document.body; ancestor = ancestor.parentElement) {
          const style = getComputedStyle(ancestor);
          const contained = /(?:paint|layout|strict|content)/.test(style.contain);
          const prefixedBackdropFilter = style.getPropertyValue("-webkit-backdrop-filter");
          if (style.transform !== "none" || style.perspective !== "none" || style.filter !== "none"
              || style.backdropFilter !== "none"
              || (prefixedBackdropFilter && prefixedBackdropFilter !== "none") || contained) {
            return ancestor;
          }
        }
        return null;
      };
      const placeTooltip = (tooltip, pointerEvent) => {
        const tooltipRect = tooltip.getBoundingClientRect();
        const margin = 8;
        const gap = 12;
        const viewportWidth = document.documentElement.clientWidth;
        const viewportHeight = document.documentElement.clientHeight;
        const right = pointerEvent.clientX + gap;
        const leftOfPointer = pointerEvent.clientX - tooltipRect.width - gap;
        const below = pointerEvent.clientY + gap;
        const above = pointerEvent.clientY - tooltipRect.height - gap;
        const left = Math.max(margin, Math.min(
          right + tooltipRect.width <= viewportWidth - margin ? right : leftOfPointer,
          viewportWidth - tooltipRect.width - margin
        ));
        const top = Math.max(margin, Math.min(
          below + tooltipRect.height <= viewportHeight - margin ? below : above,
          viewportHeight - tooltipRect.height - margin
        ));
        const containingBlock = fixedContainingBlock(tooltip);
        const containingRect = containingBlock?.getBoundingClientRect();
        const originLeft = containingRect ? containingRect.left + containingBlock.clientLeft : 0;
        const originTop = containingRect ? containingRect.top + containingBlock.clientTop : 0;
        tooltip.style.left = `${left - originLeft}px`;
        tooltip.style.top = `${top - originTop}px`;
      };
      const closeTooltip = (wrapper, dismissed = false) => {
        wrapper.classList.toggle("tooltip-dismissed", dismissed);
      };

      document.querySelectorAll(".term-with-help").forEach((wrapper) => {
        const tooltip = wrapper.querySelector(".term-tooltip");
        wrapper.addEventListener("pointerenter", (event) => placeTooltip(tooltip, event));
        wrapper.addEventListener("pointermove", (event) => placeTooltip(tooltip, event));
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


    function loadObjectConfig() {
      OBJECTS = readEmbeddedJson("object-config");
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

    function readEmbeddedJson(id) {
      const element = document.getElementById(id);
      if (!element) throw new Error(`The page is missing its embedded data: ${id}`);
      return JSON.parse(element.textContent);
    }

    function loadTemplates() {
      for (const [name, id] of Object.entries(TEMPLATE_IDS)) {
        const element = document.getElementById(id);
        if (!element) throw new Error(`The page is missing its embedded template: ${id}`);
        templates[name] = element.textContent.trimStart();
      }
    }

    // Fills a template. {{NAME}} takes its value from values, {{@key}} is one
    // catalog entry, and {{MESSAGES:prefix}} is a dict literal of every catalog
    // entry under a prefix. The Python wizard fills templates the same way.
    function applyTemplate(template, values) {
      return template.replace(/{{(?:([A-Z0-9_]+)|@([a-z0-9.-]+)|MESSAGES:([a-z]+))}}/g, (match, name, entry, prefix) => {
        if (entry) return wizardText(entry);
        if (prefix) return JSON.stringify(wizardMessages(prefix), null, 4);
        if (!Object.hasOwn(values, name)) {
          throw new Error(`Missing template value: ${name}`);
        }
        return values[name];
      });
    }

    // Returns a template from the page with its catalog text filled in.
    function bundleFile(name) {
      return applyTemplate(requireTemplate(name), {});
    }

    function requireTemplate(name) {
      if (!templates[name]) {
        throw new Error(`Template not loaded: ${name}`);
      }
      return templates[name];
    }

    let textEntries = null;

    function loadTextEntries() {
      if (!textEntries) textEntries = readEmbeddedJson("wizard-text");
      return textEntries;
    }

    function wizardMessages(prefix) {
      return Object.fromEntries(
        Object.entries(loadTextEntries()).filter(([key]) => key.startsWith(`${prefix}.`)),
      );
    }

    // Reads one entry of the shared wording that the page embeds, filling each
    // {{NAME}} from values. The Python wizard reads the same entries from
    // wizard-text.txt.
    function wizardText(key, values = {}) {
      const entries = loadTextEntries();
      if (!Object.hasOwn(entries, key)) {
        throw new Error(`Missing wizard text: ${key}`);
      }
      return entries[key].replace(/{{([A-Z0-9_]+)}}/g, (match, name) =>
        Object.hasOwn(values, name) ? String(values[name]) : match);
    }

    // Like wizardText, for text that goes into innerHTML. The wording and the
    // values are escaped, and `code` spans become <code> elements.
    function wizardHtml(key, values = {}) {
      return wizardText(key).split(/({{[A-Z0-9_]+}})/).map((piece) => {
        const placeholder = /^{{([A-Z0-9_]+)}}$/.exec(piece);
        if (placeholder && Object.hasOwn(values, placeholder[1])) {
          return escapeHtml(String(values[placeholder[1]]));
        }
        return escapeHtml(piece).replace(/`([^`]+)`/g, "<code>$1</code>");
      }).join("");
    }

    // Entries that differ by number come as KEY-one and KEY-many.
    function pluralKey(key, count) {
      return `${key}-${count === 1 ? "one" : "many"}`;
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
      state.slurm.condorMemory = numericFieldValue("condorMemory", 2048);
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
      const bytesPerEvent = (value) => wizardText("size.bytes-per-event", { VALUE: value });
      if (bytes === 0) return bytesPerEvent("0");
      if (bytes >= 1000) return wizardText("size.kilobytes-per-event", { VALUE: (bytes / 1000).toPrecision(2) });
      if (bytes >= 100) return bytesPerEvent(Math.round(bytes / 10) * 10);
      if (bytes >= 10) return bytesPerEvent(Math.round(bytes));
      return bytesPerEvent(bytes.toPrecision(2));
    }

    function costClass(bytes) {
      return bytes >= 1000 ? "cost-high" : "cost-normal";
    }

    // A bar on a log scale, from 1 B to 10 kB per event, next to the number.
    // The number carries the meaning, so the bar is hidden from screen readers.
    function costMarkup(bytes) {
      const fraction = bytes > 0 ? Math.min(1, Math.max(0.04, Math.log10(bytes) / 4)) : 0;
      return `<span class="cost-bar" aria-hidden="true"><span style="width: ${Math.round(fraction * 100)}%"></span></span>` +
        `<span class="cost-value">${escapeHtml(formatBytesPerEvent(bytes))}</span>`;
    }

    function updateCost(output, bytes) {
      output.className = `cost ${costClass(bytes)}`;
      output.innerHTML = costMarkup(bytes);
    }

    function updateSizeEstimates() {
      const total = formatBytesPerEvent(estimatedTotalBytesPerEvent());
      ["objectSizeEstimate", "variableSizeEstimate"].forEach((id) => {
        const output = document.getElementById(id);
        if (output) output.textContent = total;
      });
      Object.keys(OBJECTS).forEach((key) => {
        const output = document.getElementById(`obj-size-${key}`);
        if (output) updateCost(output, estimatedObjectBytesPerEvent(key));
      });
      const activeOutput = document.getElementById("activeObjectSizeEstimate");
      if (activeOutput && state.activeVariableObject) {
        updateCost(activeOutput, estimatedObjectBytesPerEvent(state.activeVariableObject));
      }
    }

    function isObjectAvailable(key) {
      return !(OBJECTS[key].requiresJetmod1 && state.inputFormat === "PHYSLITE");
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

    function objectNote(kind, key, values) {
      const icon = kind === "warning" ? '<i class="bi bi-exclamation-triangle" aria-hidden="true"></i> ' : "";
      return `<li class="object-note object-note-${kind}">${icon}${wizardHtml(key, values)}</li>`;
    }

    function dependencyNotes(key) {
      const dependents = key === "Event"
        ? []
        : dependentObjectsFor(key).filter((dependent) => state.selectedObjects.has(dependent));
      const dependencies = dependenciesFor(key).filter((dependency) => dependency !== "Event");
      const notes = key === "Event" ? [objectNote("info", "objects.note-always")] : [];
      if (dependencies.length === 1) {
        notes.push(objectNote("info", "objects.note-requires-one", { OBJECT: OBJECTS[dependencies[0]].title }));
      } else if (dependencies.length) {
        notes.push(objectNote("info", "objects.note-requires-many", { COUNT: dependencies.length }));
      }
      if (dependents.length) {
        notes.push(objectNote("info", "objects.note-needed-by", {
          OBJECTS: dependents.map((dependent) => OBJECTS[dependent].title).join(", "),
        }));
      }
      return notes;
    }

    function renderObjects() {
      objectList.innerHTML = Object.entries(OBJECTS).map(([key, object]) => {
        const unavailable = !isObjectAvailable(key);
        const checked = state.selectedObjects.has(key) && !unavailable;
        const notes = [
          ...dependencyNotes(key),
          unavailable ? objectNote("warning", "objects.note-unavailable") : "",
        ].filter(Boolean).join("");
        const descriptionIds = [`obj-desc-${key}`, `obj-meta-${key}`];
        if (notes) descriptionIds.push(`obj-status-${key}`);
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
                  ${notes ? `<ul class="object-notes" id="obj-status-${key}">${notes}</ul>` : ""}
                  <div class="object-meta" id="obj-meta-${key}">
                    <span class="object-variable-count">${wizardHtml(pluralKey("objects.variable-count", availableVariableEntries(key).length), { COUNT: availableVariableEntries(key).length })}</span>
                    ${unavailable ? "" : `<span class="cost ${costClass(estimatedObjectBytesPerEvent(key))}" id="obj-size-${key}" title="${wizardHtml("objects.size-title")}">${costMarkup(estimatedObjectBytesPerEvent(key))}</span>`}
                  </div>
                </div>
              </div>
            </label>
          </div>`;
      }).join("");
      const dataNote = document.getElementById("objectsDataNote");
      dataNote.hidden = state.sampleType !== "DATA";
      dataNote.textContent = wizardText("objects.note-labels-omitted");
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
          const announcement = input.checked
            ? (relatedTitles ? "announce.object-selected-with" : "announce.object-selected")
            : (relatedTitles ? "announce.object-off-with" : "announce.object-off");
          announce(wizardText(announcement, { OBJECT: objectTitle, RELATED: relatedTitles }));
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
        variableAccordion.innerHTML = `<div class="alert alert-warning">${wizardHtml("variables.select-object-first")}</div>`;
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
          const notes = [
            required && available ? `<span class="variable-note" id="var-required-${activeKey}-${name}">${wizardHtml("variables.note-required")}</span>` : "",
            !available ? `<span class="variable-note" id="var-unavailable-${activeKey}-${name}">${wizardHtml("variables.note-data-unavailable")}</span>` : "",
          ].join("");
          return `
            <tr class="${available ? "" : "opacity-50"}">
              <td class="variable-check">
                <input class="form-check-input variable-toggle" type="checkbox" value="${name}" data-object="${activeKey}" id="var-${activeKey}-${name}" aria-labelledby="var-label-${activeKey}-${name}" aria-describedby="${detailIds.join(" ")}" ${checked ? "checked" : ""} ${required || !available ? "disabled" : ""}>
              </td>
              <th scope="row" class="variable-name-cell">
                <label for="var-${activeKey}-${name}"><code class="variable-name" id="var-label-${activeKey}-${name}">${name}</code></label>
                ${notes}
              </th>
              <td class="variable-branch" id="var-branch-${activeKey}-${name}">${branchText}</td>
            </tr>`;
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
            <label class="form-label variable-object-select-label" for="variableObjectSelect">${wizardHtml("term.object")}</label>
            <select class="form-select variable-object-select" id="variableObjectSelect">${options}</select>
            <div class="variable-tab-list" role="tablist" aria-label="${wizardHtml("objects.output-label")}" aria-orientation="vertical">${tabs}</div>
          </div>
          <section class="variable-panel" id="variable-panel" role="tabpanel" tabindex="0" aria-labelledby="variable-tab-${activeKey}">
            <h3 class="h5">${wizardHtml("variables.panel-heading", { OBJECT: activeObject.title })} <span class="cost ${costClass(estimatedObjectBytesPerEvent(activeKey))}" id="activeObjectSizeEstimate">${costMarkup(estimatedObjectBytesPerEvent(activeKey))}</span></h3>
            <table class="variable-table">
              <thead><tr>
                <th scope="col" class="variable-check"><span class="visually-hidden">${wizardHtml("variables.column-include")}</span></th>
                <th scope="col">${wizardHtml("term.variable")}</th>
                <th scope="col">${wizardHtml("variables.column-source")}</th>
              </tr></thead>
              <tbody>${variables}</tbody>
            </table>
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
        announce(wizardText("announce.showing-variables", { OBJECT: OBJECTS[event.target.value].title }));
      });

      const tabButtons = Array.from(variableAccordion.querySelectorAll(".variable-tab"));
      tabButtons.forEach((button, index) => {
        button.addEventListener("click", () => {
          activateObject(button.dataset.object, `#variable-tab-${button.dataset.object}`);
          announce(wizardText("announce.showing-variables", { OBJECT: OBJECTS[button.dataset.object].title }));
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
          announce(wizardText("announce.showing-variables", { OBJECT: OBJECTS[nextKey].title }));
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
      nextButton.textContent = wizardText(state.step === 3 ? "ui.review" : "ui.next");
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
      const formatNote = wizardText(
        config.inputFormat === "PHYSLITE" ? "bundle.format-note-physlite" : "bundle.format-note-jetmod1",
      );
      const sampleNote = wizardText(
        config.sampleType === "DATA" ? "bundle.sample-note-data" : "bundle.sample-note-simulation",
      );
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
      const steps = state.slurm.scheduler === "condor"
        ? ["run.condor-extract", "run.condor-nodes", "run.condor-start"]
        : ["run.slurm-copy", "run.slurm-start", "run.slurm-stop"];
      document.getElementById("slurmRunInstructions").innerHTML =
        steps.map((key) => `<li>${wizardHtml(key)}</li>`).join("");
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
      slurmScriptHighlight.innerHTML = state.slurm.enabled ? highlightPython(slurmScript) : wizardText("generate.script-off");
      document.getElementById("runInstructions").hidden = !state.slurm.enabled;
      updateRunInstructions();
      const condor = state.slurm.scheduler === "condor";
      document.getElementById("slurmScriptHighlightHeading").textContent =
        wizardText(condor ? "generate.condor-heading" : "generate.slurm-heading");
      document.getElementById("downloadSlurmScript").innerHTML = `<i class="bi bi-download me-1" aria-hidden="true"></i>${wizardHtml(condor ? "generate.download-condor" : "generate.download-slurm")}`;
      generationReady = true;
      setDownloadButtonsEnabled(true);
      const slurmSummary = !state.slurm.enabled
        ? wizardText("summary.batch-off")
        : condor
          ? wizardText(pluralKey("summary.condor-cores", state.slurm.condorCpus), { CORES: state.slurm.condorCpus, MEMORY: state.slurm.condorMemory })
          : wizardText(pluralKey("summary.slurm-nodes", state.slurm.nodes), { NODES: state.slurm.nodes });
      const objectSummary = Object.keys(config.objects).map((key) => {
        const title = escapeHtml(OBJECTS[key].title);
        const variableCount = Object.keys(config.objects[key].aliases).length;
        return `<li>${title}: ${wizardHtml(pluralKey("objects.variable-count", variableCount), { COUNT: variableCount })}</li>`;
      }).join("");
      const manifestSummary = state.slurm.enabled
        ? wizardHtml("summary.manifest-on", { PATH: state.slurm.inputManifest })
        : wizardHtml("summary.manifest-off");
      const objectCount = Object.keys(config.objects).length;
      const objectsTotal = wizardHtml(pluralKey("summary.objects-total", objectCount), {
        COUNT: objectCount,
        SIZE: formatBytesPerEvent(estimatedTotalBytesPerEvent()),
      });
      const sampleName = wizardHtml(config.sampleType === "MC" ? "sample.name-simulation" : "sample.name-data");
      summary.innerHTML = `
        <dl class="review-list">
          <dt>${wizardHtml("summary.input")}</dt>
          <dd>${escapeHtml(config.inputFormat)}, ${sampleName}</dd>
          <dt>${wizardHtml("summary.objects")}</dt>
          <dd>${objectsTotal}
            <details class="review-objects"><summary>${wizardHtml("summary.objects-show")}</summary><ul>${objectSummary}</ul></details>
          </dd>
          <dt>${wizardHtml("batch.heading")}</dt>
          <dd>${escapeHtml(slurmSummary)}</dd>
          <dt>${wizardHtml("term.input-manifest")}</dt>
          <dd>${manifestSummary}</dd>
        </dl>`;
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
        announce(wizardText("announce.input-set", {
          FORMAT: state.inputFormat,
          SAMPLE: wizardText(state.sampleType === "MC" ? "sample.name-simulation" : "sample.name-data"),
        }));
      });
    });

    document.getElementById("selectRecommended").addEventListener("click", () => {
      state.selectedObjects = new Set(Object.keys(OBJECTS).filter((key) => OBJECTS[key].recommended && isObjectAvailable(key)));
      ensureDependencies();
      renderObjects();
      renderVariables();
      updateGeneratedScript();
      announce(wizardText("announce.recommended-selected"));
    });

    document.getElementById("selectAll").addEventListener("click", () => {
      state.selectedObjects = new Set(Object.keys(OBJECTS).filter(isObjectAvailable));
      ensureDependencies();
      renderObjects();
      renderVariables();
      updateGeneratedScript();
      announce(wizardText("announce.all-selected"));
    });

    document.getElementById("restoreDefaults").addEventListener("click", () => {
      Object.entries(OBJECTS).forEach(([key, object]) => {
        if (state.selectedObjects.has(key)) state.selectedVariables[key] = new Set(availableVariableEntries(key).map(([name]) => name));
      });
      renderVariables();
      updateGeneratedScript();
      announce(wizardText("announce.variables-restored"));
    });

    document.querySelectorAll(".slurm-input, #enableSlurm").forEach((input) => {
      input.addEventListener("input", updateGeneratedScript);
      input.addEventListener("change", updateGeneratedScript);
    });

    document.getElementById("enableSlurm").addEventListener("change", (event) => {
      announce(wizardText(event.target.checked ? "announce.batch-on" : "announce.batch-off"));
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
        announce(wizardText("announce.check-form"));
        return false;
      }
      const invalidStep = firstInvalid.closest(".wizard-step");
      if (invalidStep) setStep(Number(invalidStep.dataset.step), false);
      const hiddenGroup = firstInvalid.closest("details");
      if (hiddenGroup) hiddenGroup.open = true;
      const error = document.getElementById(firstInvalid.dataset.errorId);
      window.requestAnimationFrame(() => firstInvalid.focus());
      announce(wizardText("announce.cannot-continue", {
        REASON: error ? error.textContent.trim() : firstInvalid.validationMessage,
      }));
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

    // Batch jobs run from the bundle directory, so only a relative output path
    // that stays inside it can be shipped as an empty directory. Without batch
    // generation the converter's output location is chosen at run time.
    function bundleOutputDir() {
      if (!state.slurm.enabled) return "output";
      const value = (state.slurm.outputBase || "").trim();
      if (/^[/~$]/.test(value)) return null;
      const parts = value.split("/").filter((part) => part && part !== ".");
      if (!parts.length || parts.includes("..")) return null;
      return parts.join("/");
    }

    function bundleReadme() {
      const pythonName = generatedPythonName().split("/").pop();
      const scheduler = state.slurm.scheduler === "condor" ? "condor" : "slurm";
      const enabled = state.slurm.enabled;
      return applyTemplate(requireTemplate("readme"), {
        PYTHON_NAME: pythonName,
        OUTPUT_DIR: bundleOutputDir() || state.slurm.outputBase.trim(),
        MANIFEST_DESCRIPTION: wizardText(`bundle.manifest-description-${scheduler}`),
        SLURM_FILE_LINE: enabled ? `${wizardText(`bundle.file-lines-${scheduler}`)}\n` : "",
        WORKFLOW_FILE_LINE: enabled ? `${wizardText("bundle.file-lines-workflow")}\n` : "",
        SLURM_SECTION: `${wizardText(enabled ? `bundle.section-${scheduler}` : "bundle.section-no-batch")}\n`,
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
      announce(wizardText("announce.converter-download"));
    });

    document.getElementById("downloadSlurmScript").addEventListener("click", () => {
      if (!generationReady || !state.slurm.enabled || !slurmScriptOutput.value || !formIsValid()) return;
      const blob = new Blob([slurmScriptOutput.value], { type: "text/x-shellscript" });
      downloadBlob(blob, batchFilename());
      announce(wizardText(state.slurm.scheduler === "condor" ? "announce.condor-download" : "announce.slurm-download"));
    });

    document.getElementById("downloadBundle").addEventListener("click", () => {
      if (!generationReady || !scriptOutput.value || !formIsValid()) return;
      try {
        const pythonName = generatedPythonName().split("/").pop();
        const root = "pcdf-ntuple";
        const files = [
          { name: `${root}/`, content: "", type: "directory", mode: 0o755 },
          { name: `${root}/code/`, content: "", type: "directory", mode: 0o755 },
          { name: `${root}/logs/`, content: "", type: "directory", mode: 0o755 },
          { name: `${root}/code/${pythonName}`, content: scriptOutput.value, mode: 0o755 },
        ];
        const outputDir = bundleOutputDir();
        if (outputDir) {
          files.push({ name: `${root}/${outputDir}/`, content: "", type: "directory", mode: 0o755 });
        }
        if (state.slurm.enabled) {
          files.push({
            name: `${root}/code/${batchFilename()}`,
            content: slurmScriptOutput.value,
            mode: 0o755,
          });
          if (state.slurm.scheduler === "condor") {
            files.push({
              name: `${root}/code/run-pcdf-condor-job.sh`,
              content: bundleFile("condorJob"),
              mode: 0o755,
            });
          }
          files.push({
            name: `${root}/run-pcdf.sh`,
            content: bundleFile("workflowShell"),
            mode: 0o755,
          });
          files.push({
            name: `${root}/code/run-pcdf.py`,
            content: bundleFile("workflowPython"),
            mode: 0o755,
          });
        }
        files.push({
          name: `${root}/code/make-manifest.py`,
          content: bundleFile("manifest"),
          mode: 0o755,
        });
        files.push({ name: `${root}/README_SUBMIT.md`, content: bundleReadme() });
        downloadBlob(createTarArchive(files), "pcdf-ntuple-bundle.tar");
        announce(wizardText("announce.bundle-download"));
      } catch (error) {
        console.error(error);
        announce(wizardText("announce.bundle-failed", { ERROR: error.message }));
      }
    });


    function initWizard() {
      initAppearance();
      initTermHelp();
      initKeyboardShortcuts();
      try {
        loadObjectConfig();
        loadTemplates();
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
        const message = wizardText("error.load-failed", { ERROR: error.message });
        scriptHighlight.textContent = message;
        slurmScriptHighlight.textContent = message;
        announce(message);
        console.error(error);
      }
    }

    setDownloadButtonsEnabled(false);
    initWizard();
