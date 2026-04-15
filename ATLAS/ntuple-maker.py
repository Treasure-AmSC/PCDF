#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
# "rich", "uproot", "numpy", "awkward", "numba", "pyarrow"
# ]
# ///

import uproot as up
import awkward as ak
import numpy as np
import numba as nb
from rich import print
from pathlib import Path

point = "[green][b]‣[/b][/green]"


# Make it easier to refer to certain things
def ei(var):
    return f"EventInfoAuxDyn.{var}"


def jet(var):
    return f"AnalysisJetsAuxDyn.{var}"


def lrjet(var):
    return f"AnalysisLargeRJetsAuxDyn.{var}"


def jetr(var):
    return f"AntiKt4EMPFlowJetsAuxDyn.{var}"


def const(var, charged):
    charged_prefix = "CHSGChargedParticleFlowObjectsAuxDyn"
    neutral_prefix = "CHSGNeutralParticleFlowObjectsAuxDyn"
    if charged:
        return f"{charged_prefix}.{var}"
    else:
        return f"{neutral_prefix}.{var}"


def track(var):
    return f"InDetTrackParticlesAuxDyn.{var}"


def elec(var):
    return f"AnalysisElectronsAuxDyn.{var}"


def muon(var):
    return f"AnalysisMuonsAuxDyn.{var}"


def photon(var):
    return f"AnalysisPhotonsAuxDyn.{var}"


def met(var):
    return f"MET_Core_AnalysisMETAuxDyn.{var}"


# Package up branches to read for each object
event_aliases = {
    "runNumber": ei("runNumber"),
    "eventNumber": ei("eventNumber"),
    "beamX": ei("beamPosX"),
    "beamY": ei("beamPosY"),
    "beamZ": ei("beamPosZ"),
}

jet_aliases = {
    "pt": jet("pt"),
    "eta": jet("eta"),
    "phi": jet("phi"),
    "m": jet("m"),
    "flavor": jet("PartonTruthLabelID"),
    "constLinks": jetr("constituentLinks"),
    "trackLinks": jet("GhostTrack"),
}

largeRjet_aliases = {
    "pt": lrjet("pt"),
    "eta": lrjet("eta"),
    "phi": lrjet("phi"),
    "m": lrjet("m"),
    "truth": lrjet("R10TruthLabel_R22v1"),
}

c_const_aliases = {
    "pt": const("pt", True),
    "eta": const("eta", True),
    "phi": const("phi", True),
    "m": const("m", True),
}

n_const_aliases = {
    "pt": const("pt", False),
    "eta": const("eta", False),
    "phi": const("phi", False),
    "m": const("m", False),
}

track_aliases = {
    "q_p": track("qOverP"),
    "theta": track("theta"),
    "phi": track("phi"),
    "d0": track("d0"),
    "z0": track("z0"),
}

elec_aliases = {
    "pt": elec("pt"),
    "eta": elec("eta"),
    "phi": elec("phi"),
    "charge": elec("charge"),
    "truth": elec("truthType"),
}

muon_aliases = {
    "pt": muon("pt"),
    "eta": muon("eta"),
    "phi": muon("phi"),
    "charge": muon("charge"),
    "truth": muon("truthType"),
}

photon_aliases = {
    "pt": photon("pt"),
    "eta": photon("eta"),
    "phi": photon("phi"),
    "charge": photon("charge"),
    "truth": photon("truthType"),
}

met_aliases = {"px": met("mpx"), "py": met("mpy")}


# Following ElementLinks
def select_per_jet(base, indexer):
    @nb.jit
    def process(b: ak.ArrayBuilder, base: ak.Array, indexer: ak.Array):
        for base_evt, idx_evt in zip(base, indexer):
            b.begin_list()
            for idx_jet in idx_evt:
                b.begin_list()
                for i in idx_jet:
                    b.append(base_evt[i])
                b.end_list()
            b.end_list()
        return b

    d = {}
    for k, v in ak.unzip(base, how=dict).items():
        b = ak.ArrayBuilder()
        d[k] = process(b, v, indexer).snapshot()
    return ak.zip(d)


def make_idx(arr):
    ndim = arr.ndim
    counts = []
    for i in range(0, ndim):
        try:
            counts.append(ak.flatten(ak.num(arr, axis=-1 - i), axis=None))
        except:  # noqa: E722
            # Get an error for the outermost dimension which we never read
            pass
    idx = ak.local_index(ak.flatten(arr, axis=None))
    for _ in range(1, ndim):
        idx = ak.unflatten(idx, counts.pop(0))
    return idx


def rec_flatten(arr):
    # Remove all but axis 0
    ndim = arr.ndim
    flat = arr
    for i in range(1, ndim):
        flat = ak.flatten(flat, axis=-1)
    return flat


with up.open("DAOD_TREASURE.treasure.pool.root") as f:
    t = f["CollectionTree"]
    event = t.arrays(expressions=event_aliases.keys(), aliases=event_aliases)
    jet = t.arrays(expressions=jet_aliases.keys(), aliases=jet_aliases)
    largeRjet = t.arrays(
        expressions=largeRjet_aliases.keys(), aliases=largeRjet_aliases
    )
    c_const = t.arrays(expressions=c_const_aliases.keys(), aliases=c_const_aliases)
    n_const = t.arrays(expressions=n_const_aliases.keys(), aliases=n_const_aliases)
    track = t.arrays(expressions=track_aliases.keys(), aliases=track_aliases)
    electron = t.arrays(expressions=elec_aliases.keys(), aliases=elec_aliases)
    muon = t.arrays(expressions=muon_aliases.keys(), aliases=muon_aliases)
    photon = t.arrays(expressions=muon_aliases.keys(), aliases=muon_aliases)
    met = t.arrays(expressions=muon_aliases.keys(), aliases=muon_aliases)

    if len(event) == 0:
        print("[b][red]ERROR: No events[/red][/b]")
        exit(0)

    print(f"{point} Read {len(event)} events")
    print(
        f"{point} Peaking at the first event to connect constituent containers and hashes."
    )
    print("  (Uproot can't read EventFormatStream...)")
    hashes, counts = np.unique(
        ak.flatten(jet.constLinks.m_persKey[0], axis=None), return_counts=True
    )
    c_count = len(c_const[0].pt)
    n_count = len(n_const[0].pt)
    if c_count == counts[0] and n_count == counts[1]:
        c_hash = hashes[0]
        n_hash = hashes[1]
    elif c_count == counts[1] and n_count == counts[0]:
        c_hash = hashes[1]
        n_hash = hashes[0]
    else:
        print(
            f"[b][red]ERROR: There were {c_count} charged constituents and {n_count} neutral consitituents,\n"
            f"but {counts[0]} links to {hashes[0]:08X} and {counts[1]} to {hashes[1]:08X}[/red][/b]"
        )
        exit(0)
    print(
        f"  [blue]{c_hash:08X} ({c_hash})[/] corresponds to charged container and [blue]{n_hash:08X} ({n_hash})[/] to neutral"
    )
    hashes, counts = np.unique(
        ak.flatten(jet.trackLinks.m_persKey[0], axis=None), return_counts=True
    )
    if len(hashes) == 0 or len(hashes) > 2 or (len(hashes == 2) and hashes[0] != 0):
        print(
            f"[b][red]ERROR: There were {len(hashes)} different track container hashes[/][/]"
        )
        exit(0)
    print(f"  Track container hash is [blue]{hashes[1]:08X} ({hashes[1]})[/]")
    print(f"{point} Following ElementLinks")
    jet_chargedConstIdx = jet.constLinks.m_persIndex[jet.constLinks.m_persKey == c_hash]
    jet_neutralConstIdx = jet.constLinks.m_persIndex[jet.constLinks.m_persKey == n_hash]
    jet_cConst = select_per_jet(c_const, jet_chargedConstIdx)
    jet_nConst = select_per_jet(n_const, jet_neutralConstIdx)
    jet_const = ak.concatenate([jet_cConst, jet_nConst], axis=2)
    jet_track = select_per_jet(
        track, jet.trackLinks.m_persIndex[jet.trackLinks.m_persKey != 0]
    )

    print(f"{point} Writing...")
    Path("Out").mkdir()
    print(f"  {point} Events")
    eventIndex = make_idx(event.eventNumber)
    event_out = ak.zip({"eventIndex": eventIndex, **ak.unzip(event, how=dict)})
    Path("Out/Event").mkdir()
    ak.to_parquet(rec_flatten(event_out), "Out/Event/data.parquet")

    print(f"  {point} Jets")
    jetIndex = make_idx(jet.pt)
    jet_out = ak.zip(
        {
            "jetIndex": jetIndex,
            "eventIndex": eventIndex,
            "pt": jet.pt,
            "eta": jet.eta,
            "phi": jet.phi,
            "m": jet.m,
        }
    )
    Path("Out/Jet").mkdir()
    ak.to_parquet(rec_flatten(jet_out), "Out/Jet/data.parquet")  #

    print(f"  {point} Constituents")
    constIndex = make_idx(jet_const.pt)
    const_out = ak.zip(
        {
            "constIndex": constIndex,
            "jetIndex": jetIndex,
            "eventIndex": eventIndex,
            **ak.unzip(jet_const, how=dict),
        }
    )
    Path("Out/Const").mkdir()
    ak.to_parquet(rec_flatten(const_out), "Out/Const/data.parquet")

    print(f"  {point} Tracks")
    trackIndex = make_idx(jet_track.q_p)
    track_out = ak.zip(
        {
            "trackIndex": trackIndex,
            "jetIndex": jetIndex,
            "eventIndex": eventIndex,
            **ak.unzip(jet_track, how=dict),
        }
    )
    Path("Out/Track").mkdir()
    ak.to_parquet(rec_flatten(track_out), "Out/Track/data.parquet")

    print(f"  {point} Large R Jets")
    lrjetIndex = make_idx(largeRjet.pt)
    lrjet_out = ak.zip(
        {
            "jetIndex": lrjetIndex,
            "eventIndex": eventIndex,
            **ak.unzip(largeRjet, how=dict),
        }
    )
    Path("Out/LargeRJet").mkdir()
    ak.to_parquet(rec_flatten(lrjet_out), "Out/LargeRJet/data.parquet")

    print(f"  {point} Electrons")
    electronIndex = make_idx(electron.pt)
    electron_out = ak.zip(
        {
            "electronIndex": electronIndex,
            "eventIndex": eventIndex,
            **ak.unzip(electron, how=dict),
        }
    )
    Path("Out/Electron").mkdir()
    ak.to_parquet(rec_flatten(electron_out), "Out/Electron/data.parquet")

    print(f"  {point} Muons")
    muonIndex = make_idx(muon.pt)
    muon_out = ak.zip(
        {"muonIndex": muonIndex, "eventIndex": eventIndex, **ak.unzip(muon, how=dict)}
    )
    Path("Out/Muon").mkdir()
    ak.to_parquet(rec_flatten(muon_out), "Out/Muon/data.parquet")

    print(f"  {point} Photons")
    photonIndex = make_idx(photon.pt)
    photon_out = ak.zip(
        {
            "photonIndex": photonIndex,
            "eventIndex": eventIndex,
            **ak.unzip(photon, how=dict),
        }
    )
    Path("Out/Photon").mkdir()
    ak.to_parquet(rec_flatten(photon_out), "Out/Photon/data.parquet")

    print(f"  {point} MET")
    met_out = ak.zip({"eventIndex": eventIndex, **ak.unzip(met, how=dict)})
    Path("Out/MET").mkdir()
    ak.to_parquet(met_out, "Out/MET/data.parquet")
    print(f"{point} DONE")
