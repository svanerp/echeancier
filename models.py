# -*- coding: utf-8 -*-

from datetime import datetime
from dateutil.relativedelta import *
from calendar import monthrange


class Movement:
    '''
    Classe de base pour tous les mouvements planifiés

    :param amount: un montant peu importe qu'il soit positif ou négatif. Sera traité par _compute_amount !
    :param income: Si True, vérifie que amount est positif (et négatif si False).
    '''

    def __init__(self, description, amount, start_date, income=False, interval=-1, end_date=None, active=True):
        self.active = active
        self.description = description
        self.amount = Movement._compute_amount(amount, income)
        self.income = income
        self.start_date = start_date
        self.start_date_first_day = datetime(start_date.year, start_date.month, 1)
        self.day = start_date.day
        self.nb = interval
        if self.nb > 0:
            self.end_date = self.start_date + relativedelta(months=+(self.nb - 1))
        elif end_date is None:
            self.end_date = datetime(3000, 1, 1)
        else:
            self.end_date = end_date
        self.interuptible = False

    @staticmethod
    def _compute_amount(amount, income):
        if income:
            return abs(amount)
        else:
            return amount if amount < 0 else amount * -1

    def match(self, date):
        '''
        Est-ce que ce mouvement doit engendrer un payement pour le mois demandé ?
        :param date: mois demandé
        :return: True si le mois demandé est compris dans l'intervale de temps durant lequel le mouvement doit être considéré.
        '''
        # print("%s > %s : %s" % (self.end_date, date, self.end_date > date))
        res = self.end_date >= date >= self.start_date_first_day
        return res

    def __eq__(self, other):
        return self.amount == other.amount and self.description == other.description and self.day == other.day


class Income(Movement):

    def __init__(self, description, amount, start_date):
        super(Income, self).__init__(description, amount, start_date, True)


class MovementOneShot(Movement):

    def __init__(self, description, amount, start_date, income=False):
        super(MovementOneShot, self).__init__(description, amount, start_date, income, 1, start_date)
        self.end_date = start_date


class MovementAnnuel(Movement):

    def __init__(self, description, amount, start_date=datetime.now(), end_date=None):
        super(MovementAnnuel, self).__init__(description, amount, start_date, False, 12, end_date)

    def match(self, date):
        if date > self.start_date:
            return date.month == self.start_date.month
        return False

class MovementInterval(Movement):

    def __init__(self, description, amount, start_date, interval, end_date=None):
        super(MovementInterval, self).__init__(description, amount, start_date, False, interval, end_date)
        self.start_date = datetime(start_date.year, start_date.month, 1)
        self.trimestres = self._compute_trimestres()

    def _compute_trimestres(self):
        res = []
        step = int(12/self.nb)
        for r in range(step):
            res.append(r * self.nb + self.start_date.month)
        return res

    def match(self, date):
        return date.month in self.trimestres


class Souhait:

    def __init__(self, description, amount, after=None):
        self.description = description
        self.amount = amount
        self.after = after

    def compute_residual(self, date):
        return self.amount


class MovementRemboursement(Movement):

    def __init__(self, description, amount_total, start_date=datetime.now(), end_date=None, amount=None, after=None):
        # Movement.__init__(self, description, 0, start_date, False, end_date=end_date)
        # Souhait.__init__(self, description, 0)
        super(MovementRemboursement, self).__init__(description, 0, start_date, False, end_date=end_date)
        self.amount_total = amount_total
        self.amount = amount
        if end_date is not None:
            self.set_iter(self.diff_month(start_date, end_date))
        else:
            self.set_iter(self.nb)
        if amount is not None:
            self.amount = amount * -1
        self.interuptible = False
        self.after = after

    def set_iter(self, nb):
        self.nb = nb
        self.amount = (self.amount_total / nb) * -1

    def set_amount_total(self, amount_total):
        self.amount_total = amount_total
        self.amount = (amount_total / self.nb) * -1

    def compute_residual(self, date):
        n = self.diff_month(date, self.start_date)
        # return self.amount_total - n * self.amount * -1
        res = self.amount_total - n * self.amount * -1
        return res


    @staticmethod
    def diff_month(d1, d2):
        return abs((d1.year - d2.year) * 12 + d1.month - d2.month)


class MovementRemboursementNb(MovementRemboursement):

    def __init__(self, description, amount_total, start_date, nb):
        super(MovementRemboursementNb, self).__init__(description, amount_total, start_date, None, amount_total / nb)
        self.end_date = None
        self.set_iter(nb)
        self.end_date = self.start_date + relativedelta(months=self.nb - 1)

class Payement:

    def __init__(self, description, date, amount, movement):
        self.description = description
        self.date = date
        self.amount = amount
        self.mouvement = movement
        self.interuptible = False if movement is None else movement.interuptible
        self.special = False

    def __repr__(self):
        return '%s %s %s' % (self.description, self.date, self.amount)

    def __cmp__(self, other):
        return self.date.__cmp__(other.date)

    def __eq__(self, other):
        return self.date == other.date and self.description == other.description

    def __gt__(self, other):
        return self.date > other.date


class Echeancier:

    def __init__(self, nb_month, start_amount=0, start_date=datetime.now()):
        self.start_amount = start_amount
        self.start_date = datetime(start_date.year, start_date.month, 1)
        self.payments = []
        self.delta_1 = relativedelta(months=+1)
        self.balance = {}
        self.nb_month = nb_month
        self.appurements = []
        self.ended = []
        self.souhaits = []
        self.souhaits_done = []

    def compute(self, mouvements):
        # Construction des payements à partir des mouvements
        self.mouvements = mouvements
        d = self.start_date
        for i in range(self.nb_month):
            for m in mouvements:
                if not m.active:
                    continue
                # Si mouvement à retenir : création d'un payement
                if m.match(d):
                    e = datetime(d.year, d.month, Echeancier.set_day(d, m.day))
                    p = Payement(m.description, e, m.amount, m)
                    self.payments.append(p)
            d = d + self.delta_1

        # Création des paiements
        interrupted_movements = []
        current_amount = self.start_amount
        for pay in sorted(self.payments):
            so, am = self.check_souhait(current_amount, pay)
            if so is None:
                # if isinstance(pay.mouvement, MovementRemboursement):
                #     pay.description = '%s (restera %s)' % (pay.description, pay.mouvement.compute_residual(pay.date) - pay.amount * -1)
                if pay.interuptible:
                    # pay.description = '%s (reste %s)' % (pay.description, pay.mouvement.compute_residual(pay.date) - pay.amount * -1)
                    if pay.mouvement not in self.ended and pay.mouvement in self.appurements:
                        if len(self.appurements) > 0 and pay.mouvement == self.appurements[0]:
                            if pay.mouvement not in self.ended:
                                if current_amount > pay.mouvement.compute_residual(pay.date):
                                    if not 'after' in pay.mouvement.__dict__ or pay.mouvement.after < pay.date:    
                                        pay.special = True
                                        pay.amount = pay.mouvement.compute_residual(pay.date) * -1
                                        self.appurements.remove(pay.mouvement)
                                        self.ended.append(pay.mouvement)
                                        current_amount += pay.amount
                                        self.add_entry(pay, current_amount)
                                else:
                                    current_amount += pay.amount
                                    self.add_entry(pay, current_amount)
                        else:
                            current_amount += pay.amount
                            self.add_entry(pay, current_amount)
                else:
                    current_amount += pay.amount
                    self.add_entry(pay, current_amount)
            else:
                current_amount = am
                self.add_entry(so, current_amount)

    def check_souhait(self, current_amount, pay):
        '''
        Vérifie s'il est possible d'honorer un souhait à partir du cash présent à ce moment
        :param current_amount:
        :param last_date: Nécessaire à la création d'un Payement
        :return: 1. True/False : un souhait est-il possible? 2. Le montant restant après souhait honoré
        '''
        if len(self.appurements) > 0:
            s = self.appurements[0]
            # print(s)
            # TODO : aller chercher le residual
            amount = s.compute_residual(pay.date) if 'amount_total' in s.__dict__ else s.amount
            cond_one = True if s.after is not None and pay.date > s.after and current_amount > amount else False
            cond_two = True if s.after is None and current_amount > amount else False
            # if s.after is not None and pay.date > s.after and current_amount > amount:
            if cond_one or cond_two:
                    # if pay.after is not None and pay.date > pay.after:
                    pay = Payement('%s' % (s.description), pay.date, amount * -1, None)
                # elif s.after is not None and pay.date > s.after:
                #     # if 'after' in pay.__dict__ and pay.after is not None and pay.date > pay.after:
                #         pay = Payement('%s (reste %s)' % (s.description, 0), pay.date, amount * -1, None)
                # else:
                #     return None, False
                    pay.special = True
                    current_amount -= amount
                    # self.add_entry(pay, current_amount)
                    # self.souhaits.remove(s)
                    self.appurements.remove(s)
                    s.date = pay.date
                    self.souhaits_done.append(s)
                    return pay, current_amount
        return None, False

    def add_entry(self, pay, current_amount):
        if pay.date in self.balance:
            self.balance[pay.date].append(BalanceEntry(pay.date, current_amount, pay))
        else:
            self.balance[pay.date] = [BalanceEntry(pay.date, current_amount, pay)]

    @staticmethod
    def set_day(date, day):
        '''
        Renvoie day si day < nb max jours du mois indiqué sinon renvoie nb max jour du mois
        :param date: le mois à considérer, sous forme de date
        :param day: le jour du mois
        :return: jour du mois (day) ou max du mois si day > max du mois de date
        '''
        res = monthrange(date.year, date.month)
        max_day = res[1]
        return day if day < max_day else max_day

    def append_souhait(self, mov):
        found = False
        # print(mov.__class__.__name__)
        # print("Is Souhait ? %s " % isinstance(mov, Souhait))
        # print("Is MovementRemboursement ? %s " % isinstance(mov, MovementRemboursement))
        # print("Is MovementRemboursementNb ? %s " % isinstance(mov, MovementRemboursementNb))
        
        if isinstance(mov, Souhait) or isinstance(mov, MovementRemboursement) or isinstance(mov, MovementRemboursementNb):
            found = True
        if not found:
            raise ValueError('Il faut passer un Souhait ou un MovementRemboursement ! (%s)' % mov.description)
        self.appurements.append(mov)
        mov.interuptible = True


class BalanceEntry:

    def __init__(self, date, current_amount, payement):
        self.date = date
        self.current_amount = current_amount
        self.payement = payement

    def __eq__(self, other):
        return self.date == other.date and self.current_amount == other.current_amount

    def toJSON(self):
        return {
            'date': self.date,
            'current_amount': self.current_amount,
            'description': self.payement.description,
            'amount': self.payement.amount
        }


AUTHORIZED_MOVS = [MovementRemboursement, MovementRemboursementNb]
