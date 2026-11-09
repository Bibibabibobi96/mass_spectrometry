"""Explicit SolidWorks2022 STEP viewing without SaveAs or automatic discovery.

The outer owner verifies STEP records/copies, protects originals and binds the
returned native PID to its configured executable. This module is not an owner.
"""

from __future__ import annotations

from contextlib import contextmanager
import json
import math
import re
from pathlib import Path

from msplatform.io.manifest_records import file_record


class SolidWorksApplicationError(RuntimeError):
    """An explicit application boundary failure carrying actual cleanup facts."""

    def __init__(self, message, receipt):
        super().__init__(message)
        self.solidworks_receipt = receipt


def _com_modules():
    import pythoncom
    import win32com.client

    return pythoncom, win32com.client


def _value(obj, name):
    value = getattr(obj, name)
    # Pywin32 dispatch properties are callable through their default member.
    # Transform2 is an object property, not a zero-argument method; invoking
    # its default member loses the actual IMathTransform before ArrayData.
    return value() if callable(value) and not hasattr(value, "_oleobj_") else value


def _documents(app):
    # The real 2022 dispatch can expose no GetDocuments value once the last
    # document closes. Confirm the native count instead of treating an
    # enumeration error with documents present as an empty application.
    if int(_value(app, "GetDocumentCount")) == 0:
        return []
    return list(_value(app, "GetDocuments") or ())


def _identity(doc):
    return getattr(doc, "_oleobj_", doc)


def _geometry(doc):
    """Record native approximate boxes in metres, not exact boundary tolerances."""
    result = dict(
        document_type=int(_value(doc, "GetType")),
        body_count=None,
        component_count=None,
        bodies=[],
        components=[],
        unavailable=[],
        box_semantics="native approximate bounding boxes; metres",
    )
    if result["document_type"] == 1:
        try:
            bodies = list(doc.GetBodies2(0, False) or ())
            result["body_count"] = len(bodies)
            for body in bodies:
                result["bodies"].append(dict(name=str(_value(body, "Name")), box_m=list(_value(body, "GetBodyBox"))))
        except Exception as error:
            result["unavailable"].append("part bodies: " + str(error))
    elif result["document_type"] == 2:
        try:
            components = list(doc.GetComponents(False) or ())
            result["component_count"] = len(components)
            for component in components:
                row = dict(name=str(_value(component, "Name2")))
                try:
                    row["transform_array"] = list(_value(_value(component, "Transform2"), "ArrayData"))
                    row["box_m"] = list(component.GetBox(False, False))
                except Exception as error:
                    row["unavailable"] = str(error)
                result["components"].append(row)
        except Exception as error:
            result["unavailable"].append("assembly components: " + str(error))
    else:
        result["unavailable"].append("unsupported imported document type")
    return result


_MAX_INSPECTION_BYTES = 4194304


def validate_geometry_checks(checks, export_report=None):
    """Validate explicit names against the same published CAD report when supplied."""
    if (not isinstance(checks, dict) or set(checks) != {'schema_version', 'kind', 'selected_step_members'}
            or type(checks['schema_version']) is not int or checks['schema_version'] != 1
            or checks['kind'] != 'selected_solid_geometry_v1'):
        raise ValueError('unsupported selected geometry checks')
    selected = checks['selected_step_members']
    if (not isinstance(selected, list) or not 1 <= len(selected) <= 7
            or any(not isinstance(name, str) or not name or '/' in name or '\\' in name
                   or any(ord(c) < 32 for c in name) for name in selected)
            or len(set(selected)) != len(selected)):
        raise ValueError('geometry checks require1..7 unique exact STEP member names')
    if export_report is None:
        return {}
    projection = export_report.get('projection', {})
    if (type(export_report.get('schema_version')) is not int or export_report['schema_version'] != 1
            or export_report.get('role') != 'owned_assembly_step_export'
            or type(projection.get('schema_version')) is not int or projection['schema_version'] != 1
            or projection.get('role') != 'assembly_step_projection'
            or projection.get('representation') != 'physical_solids' or projection.get('length_unit') != 'mm'
            or not isinstance(projection.get('exported_members'), list)):
        raise ValueError('published physical STEP report required for geometry checks')
    rows = projection['exported_members']
    labels = [row.get('step_name') if isinstance(row, dict) else None for row in rows]
    if (any(not isinstance(name, str) or not name or '/' in name or '\\' in name
            or any(ord(c) < 32 for c in name) for name in labels)
            or len(set(labels)) != len(labels)):
        raise ValueError('published STEP member names are missing or ambiguous')
    result = {}
    for name in selected:
        matching = [row for row in rows if row.get('step_name') == name]
        if len(matching) != 1:
            raise ValueError('selected member missing or ambiguous in published report: '+name)
        result[name] = matching[0]
    return result


def _native_numeric(values, count):
    row = list(values)
    if len(row) != count or any(type(v) not in (int, float) or not math.isfinite(v) for v in row):
        raise ValueError('unexpected native numeric array shape')
    return row

def _native_cylinder(values):
    raw = _native_numeric(values, 7)
    return dict(raw_m_axis=raw, origin_mm=[v*1000 for v in raw[:3]], axis=raw[3:6], radius_mm=raw[6]*1000)

def _native_mass_properties(values):
    raw = _native_numeric(values, 12)
    return dict(raw_SI=raw, center_of_mass_local_mm=[v*1000 for v in raw[:3]],
                volume_mm3=raw[3]*1e9, area_mm2=raw[4]*1e6,
                density_argument=1.0, material_density_claim=False)

def _imported_step_name(name, expected_names):
    """Match only a bound report literal and the observed vendor suffix forms."""
    leaf = name.rsplit('/', 1)[-1]
    matches = [expected for expected in expected_names
               if re.fullmatch(re.escape(expected) + r'(?:\.step)?(?:-\d+)?', leaf)]
    if len(matches) > 1:
        raise ValueError('imported STEP member name is ambiguous in published report')
    return matches[0] if matches else None


class _InspectionIncomplete(RuntimeError):
    pass

class _InspectionBounds:
    def __init__(self):
        self.faces = self.edges = 0
        self.bytes = 65536

    def charge(self, _value):
        self.bytes += len(json.dumps(_value, allow_nan=False).encode('utf-8'))+256
        if self.bytes > _MAX_INSPECTION_BYTES:
            raise _InspectionIncomplete('4MiB diagnostic cap reached')

def _observe_native_value(row, key, getter):
    try:
        row[key] = getter()
    except Exception as error:
        row.setdefault('errors', {})[key] = (type(error).__name__+': '+str(error))[:1000]

def _inspect_selected_geometry(doc, export_report, checks):
    pc, client = _com_modules()
    result = dict(role='solidworks_selected_geometry_observations', qualification='not_granted',
                  status='observations_only', members=[], errors=[], units='raw SI plus explicit mm conversions',
                  operations_requested=dict(open=0, save=0, close=0, preferences=0, rebuild=0))
    bounds = _InspectionBounds()
    expected = validate_geometry_checks(checks, export_report)
    report_names = [row['step_name'] for row in export_report['projection']['exported_members']]
    groups = {key: [] for key in expected}
    try:
        components = list(doc.GetComponents(False) or ())
    except Exception as error:
        return dict(status='incomplete', qualification='not_granted', members=[], errors=['GetComponents: '+str(error)[:1000]])
    for component in components:
        name = str(_value(component, 'Name2'))
        key = _imported_step_name(name, report_names)
        if key in groups:
            groups[key].append((name, component))
    try:
        for key, candidates in groups.items():
            if len(candidates) != 1:
                result['errors'].append(dict(step_name=key, reason='mapping missing or ambiguous', count=len(candidates)))
                continue
            name, component = candidates[0]
            member = dict(step_name=key, native_component_name=name, source=expected[key], bodies=[])
            _observe_native_value(member, 'component_transform_raw', lambda: _native_numeric(_value(_value(component, 'Transform2'), 'ArrayData'), 16))
            try:
                info = client.VARIANT(pc.VT_BYREF | pc.VT_VARIANT, None)
                bodies = list(component.GetBodies3(0, info) or ())
                member['bodies_info'] = list(info.value) if info.value is not None else None
                member['solid_body_count'] = len(bodies)
            except Exception as error:
                member['errors'] = {'GetBodies3': (type(error).__name__+': '+str(error))[:1000]}
                bounds.charge(member)
                result['members'].append(member)
                continue
            if len(bodies) > 128:
                raise _InspectionIncomplete('128 bodies/member cap reached')
            for body_index, body in enumerate(bodies):
                body_row = dict(run_local_body_index=body_index, faces=[])
                _observe_native_value(body_row, 'mass_properties', lambda: _native_mass_properties(body.GetMassProperties(1.0)))
                try:
                    faces = list(_value(body, 'GetFaces') or ())
                    body_row['face_count'] = len(faces)
                except Exception as error:
                    body_row['errors'] = {'GetFaces': str(error)[:1000]}
                    faces = []
                for face_index, face in enumerate(faces):
                    bounds.faces += 1
                    if bounds.faces > 4096:
                        raise _InspectionIncomplete('4096 faces cap reached')
                    face_row = dict(run_local_face_index=face_index, circular_edges=[])
                    try:
                        surface = _value(face, 'GetSurface')
                        face_row['is_cylinder'] = bool(_value(surface, 'IsCylinder'))
                        if face_row['is_cylinder']:
                            face_row['cylinder'] = _native_cylinder(_value(surface, 'CylinderParams'))
                        face_row['opposite_surface_normal'] = bool(_value(face, 'FaceInSurfaceSense'))
                        face_row['uv_bounds'] = _native_numeric(_value(face, 'GetUVBounds'), 4)
                        # No UVmidpoint membership assertion: trimmed face may exclude it.
                        edges = list(_value(face, 'GetEdges') or ())
                        face_row['edge_count'] = len(edges)
                        for edge_index, edge in enumerate(edges):
                            bounds.edges += 1
                            if bounds.edges > 16384:
                                raise _InspectionIncomplete('16384 edges cap reached')
                            curve = _value(edge, 'GetCurve')
                            if _value(curve, 'IsCircle'):
                                params = _native_cylinder(_value(curve, 'CircleParams'))
                                params['center_mm'] = params.pop('origin_mm')
                                params['run_local_edge_index'] = edge_index
                                params['complete_circle_not_proven'] = True
                                face_row['circular_edges'].append(params)
                    except _InspectionIncomplete:
                        raise
                    except Exception as error:
                        face_row['error'] = (type(error).__name__+': '+str(error))[:1000]
                    bounds.charge(face_row)
                    body_row['faces'].append(face_row)
                bounds.charge({k: v for k, v in body_row.items() if k != 'faces'})
                member['bodies'].append(body_row)
            bounds.charge({k: v for k, v in member.items() if k != 'bodies'})
            result['members'].append(member)
    except _InspectionIncomplete as error:
        result['errors'].append(str(error))
        result['status'] = 'incomplete'
    if result['errors'] or any(m.get('errors') or any(b.get('errors') or any(f.get('error') for f in b['faces'])
                                                   for b in m['bodies']) for m in result['members']):
        result['status'] = 'incomplete'
    result['counts'] = dict(faces=bounds.faces, edges=bounds.edges, members_completed=len(result['members']))
    return result


class StepSession:
    """Live explicit viewer session; COM objects are not persistent artifacts."""

    def __init__(self, app, document, receipt, owned_process_exit_observer=None):
        self._app, self._document, self.receipt = app, document, receipt
        self._owned_process_exit_observer = owned_process_exit_observer

    def _confirmed_owned_exit(self, *, wait=False):
        if self._owned_process_exit_observer is None:
            return None
        observed = self._owned_process_exit_observer(wait=True) if wait else self._owned_process_exit_observer()
        if (self.receipt['session_mode'] != 'owned_child' or not isinstance(observed, dict)
                or set(observed) != {'pid', 'returncode'} or type(observed['pid']) is not int
                or observed['pid'] != self.receipt['native_pid']
                or (observed['returncode'] is not None and type(observed['returncode']) is not int)):
            raise SolidWorksApplicationError('original native handle exit identity is unconfirmed', self.receipt)
        if observed['returncode'] is None or self.receipt['template_preferences_restored'] is not True:
            return None
        self.receipt['owned_native_handle_exit'] = dict(observed)
        return observed

    def _observe_rpc_closing_exit(self, error):
        hresult = getattr(error, 'hresult', error.args[0] if error.args else None)
        if (hresult != -2147417848 or self._owned_process_exit_observer is None
                or self.receipt['session_mode'] != 'owned_child'
                or self.receipt['template_preferences_restored'] is not True):
            return None
        observations = self.receipt.setdefault('closing_rpc_observations', [])
        if len(observations) < 4:
            observations.append(dict(hresult=hresult, error=str(error)[:1000],
                source='original owned Popen.wait;5seconds diagnostic only, guards held'))
        try:
            # Validate the original PID/type before asking its same handle to wait.
            known = self._confirmed_owned_exit()
            return known if known is not None else self._confirmed_owned_exit(wait=True)
        except Exception as secondary:
            self.receipt['closing_native_wait_error'] = repr(secondary)[:1000]
            error.add_note('Original owned native handle wait secondary: '+repr(secondary))
            return None

    def _observe_post_close_count_exit(self, error, remaining):
        """Resolve only the final dynamic count-lookup race with the original handle.

        Pywin32 dynamic.__getattr__ can discard a failed OLE name lookup and
        raise this exact AttributeError. It is not evidence of OS exit or RPC.
        """
        if (type(error) is not AttributeError
                or error.args != ('SldWorks.Application.30.GetDocumentCount',)
                or self.receipt.get('session_mode') != 'owned_child'
                or self._owned_process_exit_observer is None
                or self.receipt.get('template_preferences_restored') is not True
                or self.receipt.get('owned_documents_closed') is not True
                or self.receipt.get('cleanup_errors') != [] or remaining != []):
            return None
        diagnostic = dict(phase='post_owned_close_application_count',
            candidate='dynamic_count_unavailable_not_proven_rpc',
            error=dict(type=type(error).__name__, repr=repr(error)[:1000],
                args=list(error.args), hresult=getattr(error, 'hresult', None), chain=[]),
            native_exit=None, source='original owned Popen;5seconds diagnostic only')
        previous = error
        seen = {id(error)}
        for _ in range(4):
            current = previous.__cause__ or previous.__context__
            if current is None or id(current) in seen:
                break
            diagnostic['error']['chain'].append(dict(type=type(current).__name__,
                repr=repr(current)[:1000], hresult=getattr(current, 'hresult', None),
                relation='cause' if previous.__cause__ is not None else 'context'))
            seen.add(id(current))
            previous = current
        self.receipt['post_close_count_observation'] = diagnostic
        try:
            known = self._confirmed_owned_exit()
            if known is None:
                known = self._confirmed_owned_exit(wait=True)
            diagnostic['native_exit'] = known
            return known
        except Exception as secondary:
            diagnostic['wait_error'] = dict(type=type(secondary).__name__, repr=repr(secondary)[:1000])
            error.add_note('Original owned native handle wait secondary: '+repr(secondary))
            return None

    def inspect(self, *, checks=None, export_report=None):
        """Return observed import/geometry facts; never save or infer qualification."""
        if checks is not None:
            validate_geometry_checks(checks, export_report)
            if int(_value(self._app, 'GetProcessID')) != self.receipt['native_pid'] or not self.document_is_open():
                raise SolidWorksApplicationError('original document/PID identity lost before inspection', self.receipt)
        self.receipt["geometry"] = _geometry(self._document)
        if checks is not None:
            _observe_native_value(self.receipt, 'document_path_observed', lambda: str(_value(self._document, 'GetPathName')))
            self.receipt['selected_geometry'] = _inspect_selected_geometry(self._document, export_report, checks)
            if int(_value(self._app, 'GetProcessID')) != self.receipt['native_pid'] or not self.document_is_open():
                raise SolidWorksApplicationError('original document/PID identity lost during inspection', self.receipt)
        return self.receipt

    def document_is_open(self):
        """Observe actual document identity; an unavailable observation propagates."""
        if self._confirmed_owned_exit() is not None:
            return False
        try:
            return any(_identity(doc) == _identity(self._document) for doc in _documents(self._app))
        except Exception as error:
            if self._observe_rpc_closing_exit(error) is not None:
                return False
            raise


def _show_owned_document(app, document, receipt, pc, client):
    """Explicit cold viewer only; never select a replacement document."""
    title = str(_value(document, 'GetTitle'))
    docs = _documents(app)
    if (not title or not any(_identity(doc) == _identity(document) for doc in docs)
            or sum(str(_value(doc, 'GetTitle')) == title for doc in docs) != 1):
        receipt['display_document_identity_ambiguous'] = True
        raise SolidWorksApplicationError('owned viewer document title/identity is ambiguous', receipt)
    observation = dict(document_title=title, document_type=int(_value(document, 'GetType')),
        visible=bool(_value(document, 'Visible')), activation_requested=False, activation_errors=None,
        rebuild_requested=False, save_requested=False)
    receipt['display_observation'] = observation
    if observation['document_type'] != 2 or not observation['visible']:
        raise SolidWorksApplicationError('owned assembly viewer visibility is unconfirmed', receipt)
    active = _value(app, 'ActiveDoc')
    if active is None or _identity(active) != _identity(document):
        errors = client.VARIANT(pc.VT_BYREF | pc.VT_I4, 0)
        observation['activation_requested'] = True
        activated = app.ActivateDoc3(title, False, 1, errors)
        observation['activation_errors'] = int(errors.value)
        if (activated is None or _identity(activated) != _identity(document)
                or observation['activation_errors'] not in (0, 2)):
            raise SolidWorksApplicationError('activation did not return the original owned document', receipt)
    active = _value(app, 'ActiveDoc')
    observation['active_identity_matches'] = active is not None and _identity(active) == _identity(document)
    observation['visible'] = bool(_value(document, 'Visible'))
    if not observation['active_identity_matches'] or not observation['visible']:
        raise SolidWorksApplicationError('owned viewer activation/visibility readback differs', receipt)


def _restore_import_preferences(app, preferences, receipt):
    for key, value in preferences.items():
        if receipt['preference_restoration'].get(str(key)) is True:
            continue
        try:
            if key in (8, 9):
                if not app.SetUserPreferenceStringValue(key, value):
                    raise RuntimeError("restore returned false")
                actual = str(app.GetUserPreferenceStringValue(key))
            else:
                app.SetUserPreferenceToggle(key, value)
                actual = bool(app.GetUserPreferenceToggle(key))
            if actual != value:
                raise RuntimeError("restore readback differs")
            receipt['preference_restoration'][str(key)] = True
        except Exception as error:
            receipt['preference_restoration'][str(key)] = False
            receipt["cleanup_errors"].append("restore preference " + str(key) + ": " + str(error))
    receipt['template_preferences_restored'] = all(
        receipt['preference_restoration'].get(str(key)) is True for key in (8, 9, 111, 691))


@contextmanager
def open_step_session(step_path, *, executable, com_class, part_template, assembly_template, session_mode="new", visible=True,
                      owned_process_id=None, owned_process_exit_observer=None, display_owned_document=False):
    """Import a controlled STEP copy into an explicit2022 viewer session.

    LoadFile4 is the supported foreign-file import API, not a native ReadOnly
    flag. Read-only means no save/geometry edits here, plus outer source guards;
    IsOpenedReadOnly is reported as observed, never forced true. The context
    stays live for its caller's existing GUI lifecycle. Only documents created
    by this import are closed. An attached user application is never exited.
    owned_child attaches only to the caller's explicitly launched process;
    the caller must retain its original process handle through actual exit.
    """
    step, exe, template, assembly = map(Path, (step_path, executable, part_template, assembly_template))
    if com_class != "SldWorks.Application.30" or session_mode not in {"new", "attach", "owned_child"} or type(visible) is not bool:
        raise ValueError("explicit SolidWorks2022 class/session mode required")
    if ((session_mode == "owned_child" and (type(owned_process_id) is not int or owned_process_id <= 0))
            or (session_mode != "owned_child" and owned_process_id is not None)):
        raise ValueError("owned_child requires only its explicit original process ID")
    if (owned_process_exit_observer is not None and
            (session_mode != 'owned_child' or not callable(owned_process_exit_observer))):
        raise ValueError('native exit observer requires the original owned_child handle')
    if (type(display_owned_document) is not bool or
            (display_owned_document and (session_mode != 'owned_child' or visible is not True))):
        raise ValueError('explicit display requires a visible original owned_child viewer')
    if step.suffix.lower() not in {".step", ".stp"} or not step.is_file():
        raise ValueError("existing controlled STEP copy required")
    if exe.name.lower() != "sldworks.exe" or not exe.is_file():
        raise ValueError("explicit SolidWorks executable required")
    if not template.is_file() or template.suffix.lower() != '.prtdot':
        raise ValueError("explicit existing clean part template required")
    if not assembly.is_file() or assembly.suffix.lower() != '.asmdot':
        raise ValueError("explicit existing clean assembly template required")
    receipt = dict(
        role="solidworks_step_view",
        session_mode=session_mode,
        configured_executable=str(exe.resolve()),
        com_class=com_class,
        step_path=str(step.resolve()),
        native_pid=None,
        revision=None,
        load_errors=None,
        load_warnings=None,
        load_warnings_available=False,
        no_save_requested=True,
        read_only_semantics="guarded source copy plus no save; not a LoadFile4 readonly flag",
        template_preferences_restored=False,
        configured_templates=dict(part=str(template.resolve()), assembly=str(assembly.resolve())),
        template_records={name: file_record(path, "required_evidence")
                          for name, path in (("part", template), ("assembly", assembly))},
        template_metadata={name: dict(suffix=path.suffix.lower(), modified_time_ns=path.stat().st_mtime_ns)
                           for name, path in (("part", template), ("assembly", assembly))},
        template_preference_binding={},
        load_argument_string="",
        import_profile="3D Interconnect enabled; official2022 empty ArgString",
        import_preference_readback={},
        import_process_id=None,
        native_pid_matches_before_import=None,
        preference_restoration={},
        original_import_preferences={},
        display_owned_document_requested=display_owned_document,
        owned_documents_closed=False,
        application_exited=False,
        application_exit_semantics="ExitApp returned; outer owner confirms process exit",
        application_retained_reason=None,
        cleanup_errors=[],
    )
    pc, client = _com_modules()
    pc.CoInitialize()
    app = None
    owned = []
    before = []
    preferences = {}
    failure = None
    session = None
    import_started = False
    application_owned = session_mode == "new"
    application_identity_confirmed = True
    try:
        app = client.DispatchEx(com_class) if session_mode == "new" else client.GetActiveObject(com_class)
        receipt["native_pid"] = int(_value(app, "GetProcessID"))
        if session_mode == "owned_child":
            if receipt["native_pid"] != owned_process_id:
                receipt["application_retained_reason"] = "native_pid_mismatch"
                raise SolidWorksApplicationError("COM application differs from the original owned child", receipt)
            application_owned = True
        receipt["revision"] = str(_value(app, "RevisionNumber"))
        if receipt["revision"].split(".")[0] != "30":
            raise SolidWorksApplicationError("SolidWorks2022 revision30 required", receipt)
        before = _documents(app)
        if display_owned_document:
            if before:
                raise SolidWorksApplicationError('cold owned viewer refuses existing documents', receipt)
            app.DocumentVisible(True, 2)
            receipt['assembly_creation_visibility_requested'] = True
        if app.GetOpenDocumentByName(str(step.resolve())) is not None:
            raise SolidWorksApplicationError("controlled STEP is already open; refusing document ownership", receipt)
        preferences = {
            8: str(app.GetUserPreferenceStringValue(8)),
            9: str(app.GetUserPreferenceStringValue(9)),
            111: bool(app.GetUserPreferenceToggle(111)),
            691: bool(app.GetUserPreferenceToggle(691)),
        }
        receipt['original_import_preferences'] = {str(key): value for key, value in preferences.items()}
        # Installed2022 swconst: swDefaultTemplatePart=8 and Assembly=9 are
        # independent string preferences;111 uses both default templates.
        for key, path in ((8, template), (9, assembly)):
            target = str(path.resolve())
            accepted = bool(app.SetUserPreferenceStringValue(key, target))
            actual = str(app.GetUserPreferenceStringValue(key))
            receipt["template_preference_binding"][str(key)] = dict(
                configured=target, setter_accepted=accepted, readback=actual)
            if not accepted or actual != target:
                raise SolidWorksApplicationError("could not bind explicit clean template preference "+str(key), receipt)
        app.SetUserPreferenceToggle(111, True)
        app.SetUserPreferenceToggle(691, True)
        receipt["import_preference_readback"] = {
            str(key): bool(app.GetUserPreferenceToggle(key)) for key in (111, 691)}
        if not all(receipt["import_preference_readback"].values()):
            raise SolidWorksApplicationError("could not bind transient STEP import preferences", receipt)
        if application_owned:
            app.Visible = visible
        errors = client.VARIANT(pc.VT_BYREF | pc.VT_I4, 0)
        receipt["import_process_id"] = int(_value(app, "GetProcessID"))
        receipt["native_pid_matches_before_import"] = receipt["import_process_id"] == receipt["native_pid"]
        if not receipt["native_pid_matches_before_import"]:
            application_owned = False
            application_identity_confirmed = False
            receipt["application_retained_reason"] = "native_pid_mismatch_before_import"
            raise SolidWorksApplicationError("COM application process changed before STEP import", receipt)
        #2022 specifies empty ArgString with3D Interconnect enabled. Lowercase r
        #belongs to its disabled/translators branch, not a readonly/silent flag.
        import_started = True
        document = app.LoadFile4(str(step.resolve()), receipt["load_argument_string"],
                                 client.VARIANT(pc.VT_DISPATCH, None), errors)
        receipt["load_errors"] = int(errors.value)
        # A concurrent user document is not ours merely because it is new.
        if document is not None and all(_identity(document) != _identity(old) for old in before):
            owned = [document]
        if document is None or receipt["load_errors"] != 0:
            raise SolidWorksApplicationError("STEP LoadFile4 failed", receipt)
        if all(_identity(doc) != _identity(document) for doc in owned):
            raise SolidWorksApplicationError("imported document identity is not owned by this session", receipt)
        receipt["document_title"] = str(_value(document, "GetTitle"))
        try:
            receipt["native_is_opened_read_only"] = bool(_value(document, "IsOpenedReadOnly"))
        except Exception as error:
            receipt["native_is_opened_read_only"] = None
            receipt["readonly_observation_unavailable"] = str(error)
        _restore_import_preferences(app, preferences, receipt)
        if not receipt['template_preferences_restored']:
            raise SolidWorksApplicationError('import preferences were not restored before viewing', receipt)
        if display_owned_document:
            _show_owned_document(app, document, receipt, pc, client)
        session = StepSession(app, document, receipt, owned_process_exit_observer)
        session.inspect()
        yield session
    except BaseException as error:
        failure = error
        if import_started and not owned:
            receipt["import_ownership_unconfirmed"] = True
        if isinstance(error, Exception):
            error.solidworks_receipt = receipt
        raise
    finally:
        known_exit = None
        if session is not None:
            try:
                known_exit = session._confirmed_owned_exit()
            except Exception as error:
                receipt['cleanup_errors'].append('observe original native exit: '+str(error))
        if known_exit is not None:
            receipt['owned_documents_closed'] = True
            receipt['application_exited'] = True
            receipt['application_exit_semantics'] = 'original owned native handle exited; no CloseDoc or ExitApp call inferred'
        if (known_exit is None and app is not None and application_identity_confirmed
                and (session_mode != "owned_child" or application_owned)):
            for doc in reversed(owned):
                if receipt.get('display_document_identity_ambiguous'):
                    receipt['cleanup_errors'].append('owned document close title ambiguous; documents retained')
                    break
                try:
                    if any(_identity(current) == _identity(doc) for current in _documents(app)):
                        app.CloseDoc(str(_value(doc, "GetTitle")))
                except Exception as error:
                    known_exit = session._observe_rpc_closing_exit(error) if session is not None else None
                    if known_exit is not None:
                        break
                    receipt["cleanup_errors"].append("close owned document: " + str(error))
            remaining = None
            try:
                remaining = [] if known_exit is not None else _documents(app)
                receipt["owned_documents_closed"] = not any(
                    _identity(a) == _identity(b) for a in owned for b in remaining
                )
                if not receipt["owned_documents_closed"]:
                    receipt["cleanup_errors"].append("owned documents still open")
            except Exception as error:
                known_exit = session._observe_rpc_closing_exit(error) if session is not None else None
                if known_exit is None:
                    receipt["cleanup_errors"].append("observe document cleanup: " + str(error))
            if preferences:
                _restore_import_preferences(app, preferences, receipt)
            if application_owned and known_exit is None:
                count_access_failed = False
                try:
                    if receipt.get("import_ownership_unconfirmed"):
                        receipt["application_retained_reason"] = "import_ownership_unconfirmed"
                    else:
                        count_access_failed = True
                        application_remaining = _documents(app)
                        count_access_failed = False
                        if application_remaining:
                            receipt["application_retained_reason"] = "nonowned_documents_remain"
                        elif receipt["cleanup_errors"]:
                            receipt["application_retained_reason"] = "cleanup_not_confirmed"
                        else:
                            app.ExitApp()
                            receipt["application_exited"] = True
                except Exception as error:
                    known_exit = session._observe_rpc_closing_exit(error) if session is not None else None
                    if known_exit is None and session is not None and failure is None and count_access_failed:
                        known_exit = session._observe_post_close_count_exit(error, remaining)
                    if known_exit is None:
                        receipt["application_retained_reason"] = "application_state_unknown"
                        receipt["cleanup_errors"].append("application cleanup: " + str(error))
            elif not application_owned:
                receipt["application_retained_reason"] = "attached_user_application"
        if known_exit is not None:
            receipt['owned_documents_closed'] = True
            receipt['application_exited'] = True
            receipt['application_exit_semantics'] = 'original owned native handle exited; no CloseDoc or ExitApp call inferred'
        try:
            pc.CoUninitialize()
        except Exception as error:
            receipt["cleanup_errors"].append("COM uninitialize: " + str(error))
        if receipt["cleanup_errors"]:
            if failure is not None:
                failure.add_note("SolidWorks cleanup errors: " + repr(receipt["cleanup_errors"]))
            else:
                raise SolidWorksApplicationError("SolidWorks viewer cleanup was not fully confirmed", receipt)
