from typing import Annotated

from fastapi import APIRouter, Depends, Path

from src.config.database import connect
from src.constants.domain import Role
from src.controllers.auth import allow, current_user
from src.models import audit, scheduling
from src.schemas.inputs import PendingOrderInput, ShiftInput, TrialInput
from src.services import schedule_ops


router = APIRouter(prefix='/api/schedule')
TrialID = Annotated[int, Path(gt=0, le=9223372036854775807)]
analyst = allow(Role.ANALYST)


@router.get('', dependencies=[Depends(current_user)])
def board():
    with connect() as db:
        return schedule_ops.board(db)


@router.post('/shifts', status_code=201)
def create_shift(form: ShiftInput, user=Depends(analyst)):
    with connect() as db:
        shift = scheduling.insert_shift(db, form.model_dump(), user['email'])
        audit.record(db, user['email'], 'shift.create', shift['id'])
        return shift


@router.post('/orders', status_code=201)
def create_pending(form: PendingOrderInput, user=Depends(analyst)):
    with connect() as db:
        order = scheduling.insert_pending(db, form.model_dump(), user['email'])
        audit.record(db, user['email'], 'pending.create', order['code'])
        return order


@router.post('/trials', status_code=201)
def create_trial(form: TrialInput, user=Depends(current_user)):
    with connect() as db:
        return schedule_ops.preview(db, form.report_id, user['email'])


@router.get('/trials/{trial_id}')
def trial(trial_id: TrialID, user=Depends(current_user)):
    with connect() as db:
        return schedule_ops.trial_detail(db, trial_id)


@router.post('/trials/{trial_id}/confirm')
def confirm(trial_id: TrialID, user=Depends(analyst)):
    with connect() as db:
        return schedule_ops.confirm(db, trial_id, user['email'])
