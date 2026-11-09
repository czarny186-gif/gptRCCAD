"""Non-destructive world-space section plane, shared by drawing and picking."""
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QPushButton
from . import kernel


def clip_segments(points, plane):
    """Clip independent line pairs; keep original edge identities in the caller."""
    pts=np.asarray(points,float).reshape(-1,2,3)
    if plane is None:return pts.reshape(-1,3)
    d=pts @ np.asarray(plane[:3])+plane[3]
    keep=np.max(d,axis=1)>=-1e-7
    pts=pts[keep].copy();d=d[keep]
    crossing=(d[:,0]<0)!=(d[:,1]<0)
    if crossing.any():
        rows=np.nonzero(crossing)[0];a=pts[rows,0];b=pts[rows,1]
        q=a+(b-a)*(d[rows,0]/(d[rows,0]-d[rows,1]))[:,None]
        pts[rows,(d[rows,0]>=0).astype(int)]=q
    return pts.reshape(-1,3)


class SectionTools:
    def _build_section(self):
        from .studio import _label, _spin
        self.section_origin=self.section_normal=None
        self.section_picking=False;self.section_working=False;self._section_drag_start=None;self._section_hover_key=None
        self.section_panel,lay=self._panel(300,'Widok przekroju','x_section','Podgląd wnętrza',plain=True)
        self.section_status=_label('Wskaż płaską ścianę bryły.','small');self.section_status.setWordWrap(True);lay.addWidget(self.section_status)
        self.section_offset=_spin(0,-1e6,1e6,3,1);self.section_offset.setSuffix(' mm')
        self.section_offset.setToolTip('Głębokość przekroju od wskazanej ściany. Możesz też przeciągnąć pomarańczową strzałkę.')
        lay.addWidget(self.section_offset)
        self.section_work_button=QPushButton('PRACUJ');self.section_work_button.setObjectName('primary')
        self.section_work_button.setCheckable(True);self.section_work_button.clicked.connect(self.section_work)
        self.section_work_button.setToolTip('Ukryj strzałkę przekroju i pracuj na odsłoniętej bryle. PRZERWIJ przywraca ustawianie przekroju.')
        lay.addWidget(self.section_work_button)
        self.section_edit_buttons=[]
        row=QHBoxLayout();lay.addLayout(row)
        for text,callback in [('Inna ściana',self.section_repick),('Odwróć',self.section_flip),('Wyłącz',lambda:self.toggle_section(False))]:
            b=QPushButton(text);b.clicked.connect(lambda _=False,f=callback:f());row.addWidget(b)
            if text!='Wyłącz':self.section_edit_buttons.append(b)
        self.section_reversed=False
        self.section_offset.valueChanged.connect(self._section_update)
        self.section_panel.hide()
        self._section_controls()

    def toggle_section(self,on,cancel_tool=True):
        self.section_button.setChecked(on)
        if on:
            self.section_panel.show()
            if self.section_origin is None:self.section_repick()
            else:self._section_update()
        else:
            active=self.section_origin is not None or self.section_picking
            self.section_picking=False;self.view.section_picking=False;self.section_working=False
            self.section_origin=self.section_normal=None;self.section_reversed=False
            self._section_drag_start=None;self._section_hover_key=None
            self.section_offset.blockSignals(True);self.section_offset.setValue(0);self.section_offset.blockSignals(False)
            self.view.set_section_plane(None);self.view.section_handles=[];self.view.set_section_hover(None)
            if self.view._handle_drag is not None and self.view._handle_drag.get('id')=='section':self.view._handle_drag=None
            self.view.hover_handle=None;self.view.setCursor(Qt.ArrowCursor)
            if active and cancel_tool and self.mode is not None:
                if self.busy and self._cancel_op is not None:self._cancel_op()
                self.set_mode(None)
            self.section_panel.hide();self.view.overlay.update()
        self._section_controls();self._layout_overlays()

    def _section_controls(self):
        chosen=self.section_origin is not None and not self.section_picking
        self.section_work_button.setEnabled(chosen)
        self.section_work_button.setChecked(self.section_working)
        self.section_work_button.setText('PRZERWIJ' if self.section_working else 'PRACUJ')
        self.section_offset.setEnabled(chosen and not self.section_working)
        for button in self.section_edit_buttons:button.setEnabled(not self.section_working)
        self.section_edit_buttons[1].setEnabled(chosen and not self.section_working)

    def section_work(self,on):
        if self.section_origin is None or self.section_picking:return
        self.section_working=bool(on);self._section_drag_start=None
        self.section_status.setText('Pracuj na odsłoniętej bryle. PRZERWIJ przywraca strzałkę przekroju.' if on else 'Przeciągnij strzałkę albo wybierz inną ścianę.')
        self.view.hover_handle=None;self.view.setCursor(Qt.ArrowCursor)
        self._section_controls();self._section_update();self._layout_overlays()

    def section_repick(self):
        self.section_working=False
        self.section_picking=True;self.view.section_picking=True;self._section_hover_key=None
        self.view.set_section_plane(None);self.view.section_handles=[]
        self.section_status.setText('Najedź na płaską ścianę i kliknij lewym przyciskiem.')
        self.view.setCursor(Qt.PointingHandCursor)
        self._section_controls()

    def _section_face(self,x,y):
        hit=self.view.pick_face(x,y)
        body=self.document.get(hit[0]) if hit else None
        if body is None or body.kind!='solid':return None
        try:face,normal=kernel.face_at(body.shape,hit[1],hit[2])
        except kernel.CadError:return None
        return face,np.asarray(normal,float),np.asarray(hit[2],float)

    def section_hover(self,x,y):
        value=self._section_face(x,y)
        key=value[0].hashCode() if value else None
        if key!=self._section_hover_key:
            self._section_hover_key=key
            self.view.set_section_hover(kernel.display_mesh(value[0]) if value else None)

    def section_pick(self,x,y):
        value=self._section_face(x,y)
        if value is None:
            self.toast('Wskaż płaską ścianę bryły.');return
        _,self.section_normal,self.section_origin=value
        self.section_picking=False;self.view.section_picking=False;self.section_reversed=False
        self.view.set_section_hover(None);self.view.setCursor(Qt.ArrowCursor)
        self.section_offset.blockSignals(True);self.section_offset.setValue(0);self.section_offset.blockSignals(False)
        self.section_status.setText('Przeciągnij strzałkę. Przekrój pozostaje aktywny przy używaniu innych narzędzi.')
        self._section_controls();self._section_update()

    def section_flip(self):
        self.section_reversed=not self.section_reversed;self._section_update()

    def _section_update(self,*_):
        if self.section_origin is None or not self.section_button.isChecked():return
        n=self.section_normal
        p=self.section_origin-n*self.section_offset.value()
        keep=n if self.section_reversed else -n
        self.view.set_section_plane(np.r_[keep,-keep@p])
        self.view.section_handles=[] if self.section_working else [dict(id='section',start=p,tip=p-n,dir=-n,color=(1,.48,.05,1),label='Przekrój',min_px=64)]
        self.view.overlay.update()

    def section_dragged(self,delta):
        if self.section_working or self.section_origin is None:return
        if self._section_drag_start is None:self._section_drag_start=self.section_offset.value()
        self.section_offset.setValue(self._section_drag_start+delta)

    def section_cancel_pick(self):
        self.section_picking=False;self.view.section_picking=False
        self.view.set_section_hover(None);self.view.setCursor(Qt.ArrowCursor)
        if self.section_origin is None:self.toggle_section(False)
        else:
            self.section_status.setText('Przeciągnij strzałkę albo użyj innego narzędzia.')
            self._section_controls();self._section_update()
