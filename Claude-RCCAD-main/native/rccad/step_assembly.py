"""STEP occurrence paths, with the same editable B-Rep bodies as the flat importer."""
from collections import defaultdict

import cadquery as cq
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.TDF import TDF_Label, TDF_LabelSequence
from OCP.TDocStd import TDocStd_Document
from OCP.TopLoc import TopLoc_Location
from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ShapeTool

from . import kernel


def _labels(sequence):
    return (sequence.Value(index) for index in range(1, sequence.Length() + 1))


def _name(label):
    value = TDataStd_Name()
    if label.FindAttribute(TDataStd_Name.GetID_s(), value):
        return value.Get().ToExtString().strip()
    return ''


def _occurrences(label, parent_location, path, ids):
    definition = TDF_Label()
    referenced = XCAFDoc_ShapeTool.GetReferredShape_s(label, definition)
    if not referenced:
        definition = label
    occurrence = XCAFDoc_ShapeTool.GetShape_s(label)
    if occurrence.IsNull():
        return
    name = _name(label) or _name(definition)
    names = (*path, name)
    children = TDF_LabelSequence()
    if XCAFDoc_ShapeTool.GetComponents_s(definition, children) and children.Length():
        location = parent_location.Multiplied(occurrence.Location())
        for index, child in enumerate(_labels(children)):
            yield from _occurrences(child, location, names, (*ids, index))
        return
    placed = cq.Shape.cast(occurrence.Moved(parent_location))
    for part in placed.Solids():
        yield part, names, ids


def read_step_assembly(path):
    reader = STEPCAFControl_Reader()
    if reader.ReadFile(str(path)) != IFSelect_RetDone:
        raise kernel.CadError('Nie udało się odczytać pliku STEP.')
    document = TDocStd_Document(TCollection_ExtendedString('MDTV-XCAF'))
    if not reader.Transfer(document):
        raise kernel.CadError('Nie udało się przenieść geometrii STEP.')
    tool = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    roots = TDF_LabelSequence()
    tool.GetFreeShapes(roots)
    out, root_shapes = [], []
    for index, label in enumerate(_labels(roots)):
        shape = XCAFDoc_ShapeTool.GetShape_s(label)
        if shape.IsNull():
            continue
        flat = cq.Shape.cast(shape)
        root_shapes.append(flat)
        # Match occurrence metadata to the exact solids of this root. Fall back per
        # solid if an exporter uses a STEP representation XCAF cannot traverse.
        by_shape = defaultdict(list)
        for part, names, ids in _occurrences(label, TopLoc_Location(), (), (index,)):
            by_shape[hash(part.wrapped)].append((part, names, ids))
        for part in flat.Solids():
            matches = by_shape.get(hash(part.wrapped), ())
            metadata = None
            for candidate, names, ids in matches:
                if part.wrapped.IsSame(candidate.wrapped):
                    metadata = dict(names=list(names), indices=list(ids))
                    break
            out.append((part, 'solid', metadata))
    if root_shapes:
        surfaces = kernel._free_faces(cq.Compound.makeCompound(root_shapes))
        if surfaces:
            out.append((cq.Compound.makeCompound(surfaces), 'mesh', None))
    if not out:
        raise kernel.CadError('Plik STEP nie zawiera brył ani powierzchni.')
    return out
