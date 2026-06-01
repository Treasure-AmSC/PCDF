    const OBJECTS = {
      Event: {
        title: "Events",
        folder: "Event",
        indexName: "eventIndex",
        description: "Run/event identifiers and beam spot coordinates from the original ntuple maker.",
        recommended: true,
        requiredReason: "Event is always included to provide eventIndex links for every output folder.",
        aliases: {
          runNumber: "EventInfoAuxDyn.runNumber",
          eventNumber: "EventInfoAuxDyn.eventNumber",
          beamX: "EventInfoAuxDyn.beamPosX",
          beamY: "EventInfoAuxDyn.beamPosY",
          beamZ: "EventInfoAuxDyn.beamPosZ"
        }
      },
      Jet: {
        title: "Small-R jets",
        folder: "Jet",
        indexName: "jetIndex",
        description: "Small-radius jet four-vectors and original parton flavor label.",
        recommended: true,
        dependsOn: ["Event"],
        requiredVariables: ["pt", "eta", "phi", "m"],
        aliases: {
          pt: "AnalysisJetsAuxDyn.pt",
          eta: "AnalysisJetsAuxDyn.eta",
          phi: "AnalysisJetsAuxDyn.phi",
          m: "AnalysisJetsAuxDyn.m",
          flavor: "AnalysisJetsAuxDyn.PartonTruthLabelID"
        }
      },
      Const: {
        title: "Jet constituents",
        folder: "Const",
        indexName: "constIndex",
        description: "Charged and neutral PFO constituent four-vectors from the original ntuple maker; TREASURE only.",
        recommended: true,
        requiresTreasure: true,
        dependsOn: ["Jet"],
        requiredVariables: ["pt", "eta", "phi", "m"],
        aliases: {
          pt: ["CHSGChargedParticleFlowObjectsAuxDyn.pt", "CHSGNeutralParticleFlowObjectsAuxDyn.pt"],
          eta: ["CHSGChargedParticleFlowObjectsAuxDyn.eta", "CHSGNeutralParticleFlowObjectsAuxDyn.eta"],
          phi: ["CHSGChargedParticleFlowObjectsAuxDyn.phi", "CHSGNeutralParticleFlowObjectsAuxDyn.phi"],
          m: ["CHSGChargedParticleFlowObjectsAuxDyn.m", "CHSGNeutralParticleFlowObjectsAuxDyn.m"]
        }
      },
      Track: {
        title: "Jet ghost tracks",
        folder: "Track",
        indexName: "trackIndex",
        description: "Original per-jet track trajectory parameters reached through jet GhostTrack links.",
        recommended: true,
        dependsOn: ["Jet"],
        aliases: {
          q_p: "InDetTrackParticlesAuxDyn.qOverP",
          theta: "InDetTrackParticlesAuxDyn.theta",
          phi: "InDetTrackParticlesAuxDyn.phi",
          d0: "InDetTrackParticlesAuxDyn.d0",
          z0: "InDetTrackParticlesAuxDyn.z0"
        }
      },
      LargeRJet: {
        title: "Large-R jets",
        folder: "LargeRJet",
        indexName: "largeRJetIndex",
        description: "Large-radius jet four-vectors and original truth label.",
        recommended: true,
        dependsOn: ["Event"],
        requiredVariables: ["pt", "eta", "phi", "m"],
        aliases: {
          pt: "AnalysisLargeRJetsAuxDyn.pt",
          eta: "AnalysisLargeRJetsAuxDyn.eta",
          phi: "AnalysisLargeRJetsAuxDyn.phi",
          m: "AnalysisLargeRJetsAuxDyn.m",
          truth: "AnalysisLargeRJetsAuxDyn.R10TruthLabel_R22v1"
        }
      },
      Electron: {
        title: "Electrons",
        folder: "Electron",
        indexName: "electronIndex",
        description: "Original electron kinematics, electric charge, and truth type.",
        recommended: true,
        dependsOn: ["Event"],
        requiredVariables: ["pt", "eta", "phi"],
        aliases: {
          pt: "AnalysisElectronsAuxDyn.pt",
          eta: "AnalysisElectronsAuxDyn.eta",
          phi: "AnalysisElectronsAuxDyn.phi",
          charge: "AnalysisElectronsAuxDyn.charge",
          truth: "AnalysisElectronsAuxDyn.truthType"
        }
      },
      Muon: {
        title: "Muons",
        folder: "Muon",
        indexName: "muonIndex",
        description: "Original muon kinematics, electric charge, and truth type.",
        recommended: true,
        dependsOn: ["Event"],
        requiredVariables: ["pt", "eta", "phi"],
        aliases: {
          pt: "AnalysisMuonsAuxDyn.pt",
          eta: "AnalysisMuonsAuxDyn.eta",
          phi: "AnalysisMuonsAuxDyn.phi",
          charge: "AnalysisMuonsAuxDyn.charge",
          truth: "AnalysisMuonsAuxDyn.truthType"
        }
      },
      Photon: {
        title: "Photons",
        folder: "Photon",
        indexName: "photonIndex",
        description: "Original photon kinematics and truth type; charge is intentionally omitted because photons have no charge branch.",
        recommended: true,
        dependsOn: ["Event"],
        requiredVariables: ["pt", "eta", "phi"],
        aliases: {
          pt: "AnalysisPhotonsAuxDyn.pt",
          eta: "AnalysisPhotonsAuxDyn.eta",
          phi: "AnalysisPhotonsAuxDyn.phi",
          truth: "AnalysisPhotonsAuxDyn.truthType"
        }
      },
      MET: {
        title: "Missing ET",
        folder: "MET",
        description: "Original missing transverse momentum x/y components.",
        recommended: true,
        dependsOn: ["Event"],
        requiredVariables: ["px", "py"],
        aliases: {
          px: "MET_Core_AnalysisMETAuxDyn.mpx",
          py: "MET_Core_AnalysisMETAuxDyn.mpy"
        }
      }
    };

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
        rucioDid: "<scope:name>",
        rucioRse: "<LOCAL_RSE>",
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
      state.slurm.rucioDid = fieldValue("slurmRucioDid") || "<scope:name>";
      state.slurm.rucioRse = fieldValue("slurmRucioRse") || "<LOCAL_RSE>";
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
      const phyLiteNote = config.inputFormat === "PHYSLITE"
        ? "PHYSLITE selected: jet constituents are disabled."
        : "TREASURE selected: jet constituents can be read.";
      return `#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
# "rich", "uproot", "numpy", "awkward",
# "numba", "pyarrow", "click"
# ]
# ///

"""Convert an ATLAS ${config.inputFormat} DAOD to Parquet folders.

Generated by ATLAS/ntuple-wizard.html.
${phyLiteNote}
"""

from pathlib import Path

import awkward as ak
import click
import numba as nb
import numpy as np
import uproot as up
from rich import print

POINT = "[green][b]‣[/b][/green]"
INPUT_FORMAT = "${config.inputFormat}"
OBJECTS = ${objectConfig}

JET_LINK_ALIASES = {
    "constLinks": (
        "AntiKt4EMPFlowJetsAuxDyn."
        "constituentLinks"
    ),
    "trackLinks": "AnalysisJetsAuxDyn.GhostTrack",
}


def selected_aliases(name):
    return dict(OBJECTS[name]["aliases"])


def make_idx(arr):
    ndim = arr.ndim
    counts = []
    for i in range(0, ndim):
        try:
            sizes = ak.num(arr, axis=-1 - i)
            counts.append(ak.flatten(sizes, axis=None))
        except Exception:
            # The outermost dimension is never read.
            pass
    idx = ak.local_index(ak.flatten(arr, axis=None))
    for _ in range(1, ndim):
        idx = ak.unflatten(idx, counts.pop(0))
    return idx


def rec_flatten(arr):
    flat = arr
    for _ in range(1, arr.ndim):
        flat = ak.flatten(flat, axis=-1)
    return flat


def first_field(record):
    fields = ak.fields(record)
    if not fields:
        raise ValueError("No variables selected")
    return record[fields[0]]


def select_per_jet(base, indexer):
    @nb.jit
    def process(
        builder: ak.ArrayBuilder,
        values: ak.Array,
        links: ak.Array,
    ):
        for values_evt, links_evt in zip(values, links):
            builder.begin_list()
            for links_jet in links_evt:
                builder.begin_list()
                for link in links_jet:
                    builder.append(values_evt[link])
                builder.end_list()
            builder.end_list()
        return builder

    selected = {}
    for name, values in ak.unzip(base, how=dict).items():
        builder = ak.ArrayBuilder()
        result = process(builder, values, indexer)
        selected[name] = result.snapshot()
    return ak.zip(selected)


def split_constituent_aliases():
    charged = {}
    neutral = {}
    for name, branches in selected_aliases("Const").items():
        charged[name] = branches[0]
        neutral[name] = branches[1]
    return charged, neutral


def write_object(output, folder, payload, flatten=True):
    path = output / folder
    path.mkdir(parents=True, exist_ok=False)
    data = rec_flatten(payload) if flatten else payload
    ak.to_parquet(data, path / "data.parquet")


@click.command()
@click.argument(
    "input",
    type=click.Path(
        exists=True,
        dir_okay=False,
        resolve_path=True,
        path_type=Path,
    ),
    required=True,
)
@click.option(
    "-o",
    "--output",
    type=click.Path(
        exists=False,
        dir_okay=True,
        file_okay=False,
        path_type=Path,
    ),
    required=True,
)
def ntuple_maker(input, output):
    if output.exists():
        message = f"Output exists: {output}"
        raise click.ClickException(message)

    with up.open(input) as file:
        tree = file["CollectionTree"]
        aliases = {
            name: selected_aliases(name)
            for name in OBJECTS
        }

        if "Const" in OBJECTS:
            const_aliases = split_constituent_aliases()
            aliases["c_const"] = const_aliases[0]
            aliases["n_const"] = const_aliases[1]
            aliases["Jet"] = {
                **aliases.get("Jet", {}),
                "__jetIndexSource": "AnalysisJetsAuxDyn.pt",
                "constLinks": JET_LINK_ALIASES["constLinks"],
            }
        if "Track" in OBJECTS:
            aliases["Jet"] = {
                **aliases.get("Jet", {}),
                "__jetIndexSource": "AnalysisJetsAuxDyn.pt",
                "trackLinks": JET_LINK_ALIASES["trackLinks"],
            }

        arrays = {
            name: tree.arrays(
                expressions=object_aliases.keys(),
                aliases=object_aliases,
            )
            for name, object_aliases in aliases.items()
            if object_aliases
        }

        event = arrays["Event"]
        if len(event) == 0:
            raise click.ClickException("No events found")

        print(f"{POINT} Read {len(event)} events")
        event_index = make_idx(first_field(event))
        output.mkdir(parents=True)

        if "Event" in OBJECTS:
            print(f"  {POINT} Events")
            event_payload = {"eventIndex": event_index}
            event_payload.update(ak.unzip(event, how=dict))
            write_object(
                output,
                OBJECTS["Event"]["folder"],
                ak.zip(event_payload),
            )

        jet_index = None
        jet = arrays.get("Jet")
        if jet is not None:
            jet_index_source = (
                jet["__jetIndexSource"]
                if "__jetIndexSource" in ak.fields(jet)
                else first_field(jet)
            )
            jet_index = make_idx(jet_index_source)
            if "Jet" in OBJECTS:
                print(f"  {POINT} Jets")
                jet_payload = {
                    "jetIndex": jet_index,
                    "eventIndex": event_index,
                }
                jet_payload.update(
                    {
                        name: jet[name]
                        for name in selected_aliases("Jet")
                    }
                )
                write_object(
                    output,
                    OBJECTS["Jet"]["folder"],
                    ak.zip(jet_payload),
                )

        if "Const" in OBJECTS:
            print(f"  {POINT} Following constituent links")
            hashes, counts = np.unique(
                ak.flatten(
                    jet.constLinks.m_persKey[0],
                    axis=None,
                ),
                return_counts=True,
            )
            charged_fields = ak.fields(arrays["c_const"])
            neutral_fields = ak.fields(arrays["n_const"])
            charged_count = len(
                arrays["c_const"][0][charged_fields[0]]
            )
            neutral_count = len(
                arrays["n_const"][0][neutral_fields[0]]
            )
            if len(hashes) < 2:
                raise click.ClickException(
                    "Cannot identify charged/neutral hashes"
                )
            charged_first = charged_count == counts[0]
            neutral_second = neutral_count == counts[1]
            charged_second = charged_count == counts[1]
            neutral_first = neutral_count == counts[0]
            if charged_first and neutral_second:
                charged_hash = hashes[0]
                neutral_hash = hashes[1]
            elif charged_second and neutral_first:
                charged_hash = hashes[1]
                neutral_hash = hashes[0]
            else:
                raise click.ClickException(
                    "Constituent counts do not match hashes"
                )
            charged = select_per_jet(
                arrays["c_const"],
                jet.constLinks.m_persIndex[
                    jet.constLinks.m_persKey == charged_hash
                ],
            )
            neutral = select_per_jet(
                arrays["n_const"],
                jet.constLinks.m_persIndex[
                    jet.constLinks.m_persKey == neutral_hash
                ],
            )
            constituents = ak.concatenate(
                [charged, neutral],
                axis=2,
            )
            const_index = make_idx(first_field(constituents))
            const_payload = {
                "constIndex": const_index,
                "jetIndex": jet_index,
                "eventIndex": event_index,
            }
            const_fields = ak.unzip(constituents, how=dict)
            const_payload.update(const_fields)
            print(f"  {POINT} Constituents")
            write_object(
                output,
                OBJECTS["Const"]["folder"],
                ak.zip(const_payload),
            )

        if "Track" in OBJECTS:
            print(f"  {POINT} Following track ElementLinks")
            tracks = select_per_jet(
                arrays["Track"],
                jet.trackLinks.m_persIndex[
                    jet.trackLinks.m_persKey != 0
                ],
            )
            track_index = make_idx(first_field(tracks))
            track_payload = {
                "trackIndex": track_index,
                "jetIndex": jet_index,
                "eventIndex": event_index,
            }
            track_payload.update(ak.unzip(tracks, how=dict))
            print(f"  {POINT} Tracks")
            write_object(
                output,
                OBJECTS["Track"]["folder"],
                ak.zip(track_payload),
            )

        simple_objects = (
            "LargeRJet",
            "Electron",
            "Muon",
            "Photon",
        )
        for name in simple_objects:
            if name not in OBJECTS:
                continue
            record = arrays[name]
            object_index = make_idx(first_field(record))
            payload = {
                OBJECTS[name]["index_name"]: object_index,
                "eventIndex": event_index,
            }
            payload.update(ak.unzip(record, how=dict))
            print(f"  {POINT} {OBJECTS[name]['folder']}")
            write_object(
                output,
                OBJECTS[name]["folder"],
                ak.zip(payload),
            )

        if "MET" in OBJECTS:
            print(f"  {POINT} MET")
            met_payload = {"eventIndex": event_index}
            met_fields = ak.unzip(arrays["MET"], how=dict)
            met_payload.update(met_fields)
            write_object(
                output,
                OBJECTS["MET"]["folder"],
                ak.zip(met_payload),
                flatten=False,
            )

        print(f"{POINT} DONE")


if __name__ == "__main__":
    ntuple_maker()
`;
    }

    function buildSlurmScript() {
      const slurm = state.slurm;
      const accountLine = slurm.account
        ? `#SBATCH --account=${slurm.account}`
        : "#SBATCH --account=<NERSC_PROJECT>";
      const perlmutterCpuCores = 128;
      return `#!/bin/bash
#SBATCH --job-name=pcdf-ntuple
${accountLine}
#SBATCH --qos=${slurm.qos}
#SBATCH --constraint=cpu
#SBATCH --nodes=${slurm.nodes}
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=${perlmutterCpuCores}
#SBATCH --time=${slurm.time}
#SBATCH --output=pcdf-ntuple-%j.out
#SBATCH --error=pcdf-ntuple-%j.err

# NERSC Perlmutter wrapper from ATLAS/ntuple-wizard.html.
# CPU-only: the generated converter does not use GPUs.
# Packs conversions into one wide Slurm allocation.
# Uses GNU parallel instead of a large Slurm job array.
#
# Usage from a Perlmutter login node:
#   1. Put one input DAOD path per line in INPUT_MANIFEST.
#   2. Run: sbatch submit-pcdf-ntuple.slurm

set -euo pipefail

module load python

PYTHON_SCRIPT=${JSON.stringify(slurm.pythonPath)}
INPUT_MANIFEST=${JSON.stringify(slurm.inputManifest)}
RUCIO_DID=${JSON.stringify(slurm.rucioDid)}
RUCIO_RSE=${JSON.stringify(slurm.rucioRse)}
OUTPUT_BASE=${JSON.stringify(slurm.outputBase)}
JOBS_PER_NODE=${slurm.jobsPerNode}
PERLMUTTER_CPU_CORES=${perlmutterCpuCores}

needs_edit=0
[[ "$PYTHON_SCRIPT" == *"<"* ]] && needs_edit=1
[[ "$INPUT_MANIFEST" == *"<"* ]] && needs_edit=1
[[ "$OUTPUT_BASE" == *"<"* ]] && needs_edit=1
if [[ ! -f "$INPUT_MANIFEST" ]]; then
    [[ "$RUCIO_DID" == *"<"* ]] && needs_edit=1
    [[ "$RUCIO_RSE" == *"<"* ]] && needs_edit=1
fi
if (( needs_edit )); then
    echo "ERROR: edit account/output/input settings." >&2
    exit 2
fi

mkdir -p "$OUTPUT_BASE"
mkdir -p "$(dirname "$INPUT_MANIFEST")"

if [[ ! -f "$INPUT_MANIFEST" ]]; then
    if ! command -v rucio >/dev/null 2>&1; then
        echo "ERROR: rucio is needed for the manifest." >&2
        exit 2
    fi

    echo "Input manifest not found; querying Rucio."
    echo "Rucio DID:       $RUCIO_DID"
    echo "Local RSE:       $RUCIO_RSE"
    REPLICA_REPORT="$OUTPUT_BASE/repl-\${SLURM_JOB_ID}.txt"
    PFN_LIST="$OUTPUT_BASE/pfns-\${SLURM_JOB_ID}.txt"

    rucio list-dataset-replicas "$RUCIO_DID" \\
        | tee "$REPLICA_REPORT"
    availability=$(awk -v rse="$RUCIO_RSE" -F'|' '
        $2 ~ rse {
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", $2)
            if ($2 == rse) {
                found = $3 + 0
                total = $4 + 0
                print found "/" total
            }
        }
    ' "$REPLICA_REPORT" | head -n 1)

    if [[ -n "$availability" ]]; then
        [[ "$availability" == */0 ]] && availability=""
    fi
    if [[ -n "$availability" ]]; then
        found=\${availability%%/*}
        total=\${availability##*/}
        if [[ "$found" != "$total" ]]; then
            echo "ERROR: only $availability at $RUCIO_RSE" >&2
            exit 2
        fi
    fi

    rucio list-file-replicas \\
        --rse "$RUCIO_RSE" \\
        --pfns \\
        "$RUCIO_DID" > "$PFN_LIST"

    python - "$PFN_LIST" "$INPUT_MANIFEST" <<'PCDF_PFNS'
from pathlib import Path
from sys import argv
from urllib.parse import unquote, urlparse

pfns = Path(argv[1]).read_text().splitlines()
paths = []
for raw in pfns:
    line = raw.strip()
    if not line or line.startswith(("#", "-", "|")):
        continue
    if "://" not in line:
        paths.append(line)
        continue
    parsed = urlparse(line)
    if parsed.scheme == "file":
        paths.append(unquote(parsed.path))
    else:
        paths.append(line)

content = "\\n".join(paths)
if paths:
    content += "\\n"
Path(argv[2]).write_text(content)
PCDF_PFNS
fi

if [[ ! -s "$INPUT_MANIFEST" ]]; then
    echo "ERROR: no inputs in $INPUT_MANIFEST" >&2
    exit 2
fi

if ! command -v uv >/dev/null 2>&1; then
    echo "ERROR: uv is not on PATH; load it first." >&2
    exit 2
fi

if ! command -v parallel >/dev/null 2>&1; then
    echo "ERROR: GNU parallel is not on PATH." >&2
    exit 2
fi

if (( JOBS_PER_NODE < 1 )); then
    echo "ERROR: JOBS_PER_NODE must be at least 1" >&2
    exit 2
fi
if (( JOBS_PER_NODE > SLURM_CPUS_PER_TASK )); then
    echo "ERROR: JOBS_PER_NODE exceeds available CPUs" >&2
    exit 2
fi

CPUS_PER_CONVERSION=$((
    SLURM_CPUS_PER_TASK / JOBS_PER_NODE
))
if (( CPUS_PER_CONVERSION < 1 )); then
    echo "ERROR: zero CPUs per conversion" >&2
    exit 2
fi

USED_CPUS=$((JOBS_PER_NODE * CPUS_PER_CONVERSION))
UNUSED_CPUS=$((SLURM_CPUS_PER_TASK - USED_CPUS))
if (( UNUSED_CPUS > 0 )); then
    echo "$UNUSED_CPUS CPU(s) idle per node."
fi

export UV_CACHE_DIR="\${SCRATCH:-$HOME}/.cache/uv"
echo "Preparing uv environment once."
uv run "$PYTHON_SCRIPT" --help >/dev/null

PAYLOAD_SCRIPT="$OUTPUT_BASE/convert-\${SLURM_JOB_ID}.sh"
cat > "$PAYLOAD_SCRIPT" <<'PCDF_PAYLOAD'
#!/bin/bash
set -euo pipefail

TASK_ID="$1"
INPUT_FILE="$2"

input_name=$(basename "$INPUT_FILE")
output_name="\${input_name%.*}"
OUTPUT_DIR="$OUTPUT_BASE/\${TASK_ID}_\${output_name}"

if [[ -e "$OUTPUT_DIR" ]]; then
    echo "ERROR: output exists: $OUTPUT_DIR" >&2
    exit 2
fi

export OMP_NUM_THREADS="$CPUS_PER_CONVERSION"
echo "Task \${TASK_ID}: $INPUT_FILE -> $OUTPUT_DIR"
uv run --no-sync \\
    "$PYTHON_SCRIPT" \\
    "$INPUT_FILE" \\
    -o "$OUTPUT_DIR"
PCDF_PAYLOAD
chmod +x "$PAYLOAD_SCRIPT"

DRIVER_SCRIPT="$OUTPUT_BASE/driver-\${SLURM_JOB_ID}.sh"
cat > "$DRIVER_SCRIPT" <<'PCDF_DRIVER'
#!/bin/bash
set -euo pipefail

JOBLOG="$OUTPUT_BASE/p-\${SLURM_JOB_ID}.\${SLURM_NODEID}.log"

awk \\
    -v N="$SLURM_NODEID" \\
    -v T="$SLURM_NNODES" \\
    'NF && ((NR - 1) % T == N) {print NR "\t" $0}' \\
    "$INPUT_MANIFEST" |
parallel \\
    --colsep "\t" \\
    --jobs "$JOBS_PER_NODE" \\
    --line-buffer \\
    --joblog "$JOBLOG" \\
    "$PAYLOAD_SCRIPT" {1} {2}
PCDF_DRIVER
chmod +x "$DRIVER_SCRIPT"

export PYTHON_SCRIPT INPUT_MANIFEST OUTPUT_BASE
export RUCIO_DID RUCIO_RSE
export PAYLOAD_SCRIPT JOBS_PER_NODE CPUS_PER_CONVERSION

echo "Running on \${SLURM_NNODES} node(s)"
echo "Node list:      \${SLURM_JOB_NODELIST:-unknown}"
echo "Input manifest: $INPUT_MANIFEST"
echo "Rucio DID:       $RUCIO_DID"
echo "Local RSE:       $RUCIO_RSE"
echo "Output base:    $OUTPUT_BASE"
echo "Parallelism:    $JOBS_PER_NODE job(s)/node," \\
     "$CPUS_PER_CONVERSION CPU(s) each"

srun \\
    --no-kill \\
    --ntasks="\${SLURM_NNODES}" \\
    --ntasks-per-node=1 \\
    --cpus-per-task="\${SLURM_CPUS_PER_TASK}" \\
    --wait=0 \\
    "$DRIVER_SCRIPT"
`;
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
   The bundled Python and SLURM scripts are marked executable.
2. Either create a manifest with one DAOD path/PFN per line, or set RUCIO_DID
   and RUCIO_RSE for the dataset and local RSE used by your Rucio rule. If
   INPUT_MANIFEST is missing, the wrapper asks Rucio for local PFNs and creates
   the manifest from those replicas.
3. Edit submit-pcdf-ntuple.slurm if needed: account, manifest/Rucio DID/RSE, output base, nodes, and conversions per node. The CPUs per conversion are derived from the fixed 128 CPU cores available on each Perlmutter CPU node.
4. Submit:
   sbatch submit-pcdf-ntuple.slurm
5. Monitor:
   squeue -u $USER
` : `
Perlmutter run
--------------
SLURM generation was disabled in the wizard, so this bundle contains only the
Python converter and this README. Re-enable SLURM in the wizard if you want a
Perlmutter submission wrapper.
`;
      return `PCDF ntuple bundle
===================

Files
-----
- ${pythonName}: executable generated converter.
${state.slurm.enabled ? "- submit-pcdf-ntuple.slurm: executable NERSC Perlmutter CPU/SLURM wrapper.\n" : ""}- README_SUBMIT.md: these instructions.

Local run
---------
./${pythonName} input.pool.root -o parquet-output
${slurmSection}`;
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

    document.getElementById("downloadSlurmScript").addEventListener("click", () => {
      const blob = new Blob([slurmScriptOutput.value], { type: "text/x-shellscript" });
      downloadBlob(blob, "submit-pcdf-ntuple.slurm");
    });

    document.getElementById("downloadBundle").addEventListener("click", () => {
      const pythonName = `ntuple-maker-${state.inputFormat.toLowerCase()}.py`;
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


    ensureDependencies();
    renderObjects();
    renderVariables();
    updateGeneratedScript();
    setStep(0);