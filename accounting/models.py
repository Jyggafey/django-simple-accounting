# Copyright (C) 2011 REES Marche <http://www.reesmarche.org>
#
# This file is part of ``django-simple-accounting``.

# ``django-simple-accounting`` is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, version 3 of the License.
#
# ``django-simple-accounting`` is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with ``django-simple-accounting``. If not, see <http://www.gnu.org/licenses/>.

from django.conf import settings 
from django.db import models
from django.db.models import get_model
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.translation import ugettext_lazy as _
from django.core.exceptions import ValidationError, ImproperlyConfigured

from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes import generic

from accounting.consts import ACCOUNT_PATH_SEPARATOR
from accounting.fields import CurrencyField
from accounting.managers import AccountManager  
from accounting.exceptions import MalformedAccountTree

from datetime import datetime


class Subject(models.Model):
    """ 
    A wrapper model intended to provide an uniform interface to 'subjective models'. 
    
    A 'subjective model' is defined as one whose instances can play some specific roles
    in a financial context, such as owning an account, being charged for an invoice, and so on.
    
    This model uses Django's ``ContentType`` framework in order to allow another model 
    to define foreign-key or many-to-many relationships with a generic subjective model.
    
    For example, if the ``bar`` field in the ``Foo`` model class may relate to 
    several different subjective models (e.g. ``Person``, ``Company``, etc.), 
    just declare it as follows:
    
    class Foo(models.Model):
        # ...
        bar = models.ForeignKey(Subject)
        # ...    
    """
    content_type = models.ForeignKey(ContentType)
    object_id = models.PositiveIntegerField()
    instance = generic.GenericForeignKey(ct_field="content_type", fk_field="object_id")
    
    def __unicode__(self):
        return " %(ct)s %(instance)s" % {'ct':str(self.content_type).capitalize(), 'instance':self.instance}
    
    @property
    def accounting_system(self):
        """
        The accounting system managed by this subject, if any.
        If no accounting system has been setup for this subject, raise ``AttributeError``.
        """
        try:
            return self.account_system
        except AccountSystem.DoesNotExist:
            raise AttributeError(_(u"No accounting system has been setup for this subject %s") % self)
            

try:
    subjective_models = [get_model(*model_str.split('.')) for model_str in settings.SUBJECTIVE_MODELS]
except TypeError:
    err_msg = "The current 'SUBJECTIVE_MODELS' setting is invalid: %s \n It must contain only labels for existing models"\
        % settings.SUBJECTIVE_MODELS
    raise ImproperlyConfigured(err_msg)

# when a new instance of a subjective model is created, 
# add a corresponding ``Subject`` instance pointing to it
# TODO: deal with subjective models's instances added via fixtures
@receiver(post_save)
def subjectify(sender, instance, created, **kwargs):
    if sender in subjective_models and created:
        ct = ContentType.objects.get_for_model(sender)
        Subject.objects.create(content_type=ct, object_id=instance.pk)     
    

class AccountSystem(models.Model):
    """
    A double-entry accounting system.
    
    Each accounting system is owned by a subject (i.e. a ``Subject`` instance), who manages it;
    by design, each subject may own at most one accounting system.
    
    Essentially, an accounting system is just a way to group together a hierarchy of accounts 
    (instances of the ``Account`` model), binding them to a single subjet.
    
    Furthermore, this class implements a dictionary-like interface providing for easier navigation 
    through the account tree.
    """
    # the subject operating this accounting system
    owner = models.OneToOneField(Subject, related_name='account_system')
    # the root account of this system
    @property
    def root(self):
        # FIXME: implement caching !
        for account in self.accounts:
            if account.is_root: return account
        # if we arrived here, no root account was created for this accounting system !
        raise MalformedAccountTree(_(u"No root account was created for this account system !\n %s") % self)
    
    def __unicode__(self):
        return _(u"Accounting system for %(subject)s" % {'subject': self.owner})
    
    ## operator overloading methods
    def __getitem__(self, path):
        """
        Take a path in an account tree (as a string, with path components separated by ``ACCOUNT_PATH_SEPARATOR``)
        and return the account living at that path location.
        
        If no account exists at that location, raise ``Account.DoesNotExist``.
        
        If ``path`` is an invalid string representation of a path in a tree of accounts (see below), 
        raise ``ValueError``.
    
        Path string syntax 
        ==================    
        A valid path string must begin with a single ``ACCOUNT_PATH_SEPARATOR`` string occurrence; it must end with a string
        *different* from ``ACCOUNT_PATH_SEPARATOR`` (unless the path string is just ``ACCOUNT_PATH_SEPARATOR``). 
        Path components are separated by a single ``ACCOUNT_PATH_SEPARATOR`` string occurrence, and they represent account names.            
        """
        
        from accounting.utils import get_account_from_path
        account = get_account_from_path(path, self.root)
        return account
    
    def __setitem__(self, path, account):
        """
        Take a path in an account tree (as a string, with path components separated by ``ACCOUNT_PATH_SEPARATOR``)
        and an ``Account`` instance; add that account to the children of the account living at that path location.
          
        If the given path location is invalid (see ``__getitem__``'s docstring fo details), 
        or ``account`` is not a valid ``Account`` instance, or the parent account has already a child named 
        as the given account instance, raise ``ValueError``. 
        """ 
        from accounting.utils import get_account_from_path
        parent_account = get_account_from_path(path, self.root)
        parent_account.add_child(account)   

    
    
class Account(models.Model):
    """
    An account within a double-entry accounting system (i.e., an ``AccountSystem`` model instance).
    
    From an abstract point of view, there are two general kind of accounts:
    1) those which are stocks of money, either positive (assets) or negative (liabilities)
    2) those which represent entry-points in the system (e.g incomes) or exit-points from it (e.g. expenses)    
    
    As a data stucture, an account is essentially a collection of transactions between either:
    * two accounts in the system the account belongs to 
    * an account in the system the account belongs to and one belonging to another system 
    
    Accounts within a system are hierarchically organized in a tree-like structure; 
    an account can be merely a placeholder (just a container of subaccounts, no transactions).  
    """
    
    system = models.ForeignKey(AccountSystem, related_name='accounts')
    parent = models.ForeignKey('self', null=True, blank=True)
    name = models.CharField(max_length=128)
    kind = models.CharField(max_length=128, choices=settings.ACCOUNT_TYPES)
    placeholder = models.BooleanField(default=False)
    objects = AccountManager()
    
    def __unicode__(self):
        return _("Account %(path)s owned by %(subject)s") % {'path':self.path, 'subject':self.owner}
    
    # model-level custom validation goes here
    def clean(self):
        # check that this account belongs to the same accounting system of its parent (if any)
        if self.parent:
            try:
                assert self.system == self.parent.system
            except AssertionError:
                raise ValidationError(_(u"This account and its parent belong to different accounting systems."))
        # TODO: check that stock-like accounts (assets, liabilities) are not mixed with flux-like ones (incomes, expenses)
        # TODO: check that root accounts (and only those) have ``name=''``
        # TODO: account names can't contain ``ACCOUNT_PATH_SEPARATOR``
                
    def save(self, *args, **kwargs):
        # perform model validation
        self.full_clean()
        super(Account, self).save(*args, **kwargs)  
         
    @property
    def owner(self):
        """
        Who own this account. 
        """
        return self.system.owner
    
    @property
    def balance(self):
        """
        The balance of this account (as a signed Decimal number).
        """
        # FIXME: implement caching !
        incoming_transactions = self.incoming_transaction_set.all()
        outgoing_transactions = self.outgoing_transaction_set.all()
        
        balance = 0
        for transaction in incoming_transactions:
            balance += transaction.net_amount 
        for transaction in outgoing_transactions:
            balance -= transaction.net_amount
        return balance
    
    @property
    def path(self):
        """
        The tree path needed to reach this account from the root of the accounting system,
        as a string of components separated by the ``ACCOUNT_PATH_SEPARATOR`` character(s).
        """
        if self.is_root: # stop recursion
            return ACCOUNT_PATH_SEPARATOR
        path = Account.path(self.parent) + ACCOUNT_PATH_SEPARATOR + self.name # recursion
        return path 
    
    @property
    def is_root(self):
        """
        Return ``True`` if this account is a root one, ``False`` otherwise.
        """
        return not self.parent
    
    @property
    def root(self):
        """
        The root account of the accounting system this account belongs to.
        """
        return self.system.root        
    
    def get_child(self, name):
        """
        Return the child of this account having the name provided as argument.
        
        If no child with that name exists, raise ``Account.DoesNotExist``." 
        """      
        child = Account.objects.get(parent=self, name=name)
        return child 
    
    def get_children(self):
        """
        Return the children for this account, as a ``QuerySet``.
        """
        children = Account.objects.get(parent=self)
        return children
    
    def add_child(self, account):
        """
        Add ``account`` to this account's children accounts.
          
        If ``account`` is not a valid ``Account`` instance or this account already has  
        a child account named as the given account instance, raise ``ValueError``. 
        """
        if not isinstance(account, Account):
            raise ValueError("You can only add an ``Account`` instance as a child of another account")
        try: 
            self.get_child(name=account.name)
        except Account.DoesNotExist:
            account.parent = self
            account.save()
        else:
            raise ValueError("A child account already exists with name %s" % account.name)
    
    @property
    def ledger_entries(self):
        """
        Return the queryset of entries written to the ledger associated with this account.
        """
        return self.entry_set.all().order_by('-transaction__date',)
          
    class Meta:
        unique_together = ('parent', 'name')
        

class CashFlow(models.Model):
    """
    A money flow from/to a given account.
    
    Money flows make sense only for stock-like accounts (e.g. asset/liabilities),
    not for flux-like ones (e.g. incomes/expenses).
    
    A flow is uniquely identified by these two pieces of information:
    * the account (an ``Account`` instance) from/to which the money flows
    * the amount of the flow itself (i.e., how much money flows)
    
    The sign of the flow determines its direction: by convention, a positive flow is
    considered to be incoming, while a negative one is outgoing.  As a consequence,
    incoming flows increase the amount of the stock of money represented by the account, 
    while outgoing ones decrease it.    
    """
    # from/to where the money flows
    account = models.ForeignKey(Account, related_name='flow_set')
    # how much money flows from/to that account
    amount = CurrencyField()
    
    # model-level custom validation goes here
    def clean(self):
        # TODO: check that ``account`` is stock-like
        pass
    
    def save(self, *args, **kwargs):
        # perform model validation
        self.full_clean()
        super(CashFlow, self).save(*args, **kwargs)  
     
    @property
    def is_incoming(self):
        return self.amount > 0 
    
    @property
    def is_outgoing(self):
        return self.amount < 0
        

class Trajectory(models.Model):    
    """
    This model describes the (conceptual) path followed by a flow of money 
    within (or across) accounting systems.
    
    Since a single transaction may involve more than two accounts (a.k.a. *split transactions*),
    multiple flows of money may be needed to describe it. 
    
    So, a general transaction can be thought of as a set of money flows, 
    which, in turn, can be abstracted as *trajectories* sharing a common starting account 
    (actually, a ``CashFlow`` instance wrapping that account). 
        
    A trajectory can either be fully contained within a single accounting system, 
    or extend across (at most) two of them.  We call the former ones *internal trajectories*,
    since they describe a flow of money internal to a given accounting system; the latter ones, 
    instead, describe flows of money involving accounts belonging to different systems.
    
    By definition, the shared account - that from which all the trajectories composing a transaction
    start - must be a stock-like account (since flux-like accounts can't act as starting or ending points
    due to their own nature - they are waypoints). 
    
    A general trajectory is completely specified by these pieces of information:
    * the exit point from the first accounting system (if any) 
    * the entry point to the second accounting system (if any)
    * the target account (actually, the target *flow*)
    
    Note that entry/exit points must be flux-like accounts (e.g. incomes/expenses), 
    while the target account must be a stock-like one (e.g. assets/liabilities). 
    
    For internal trajectories, entry/exit points are missing, by definition (since they are contained within 
    a single accounting system).    
    """
    
    entry_point = models.ForeignKey(Account, null=True, blank=True)
    exit_point = models.ForeignKey(Account, null=True, blank=True)
    target = models.ForeignKey(CashFlow)
    
    # model-level custom validation goes here
    def clean(self):
        # TODO: if ``entry point`` is null, so must be ``exit_point``
        # TODO: ``entry_point`` must be a flux-like account
        # TODO: ``exit_point`` must be a flux-like account
        # TODO: ``target`` must be a stock-like account
        # TODO: ``exit_point`` must belong to the same accounting system as ``target``
        pass
        
    def save(self, *args, **kwargs):
        # perform model validation
        self.full_clean()
        super(Trajectory, self).save(*args, **kwargs)
           
    @property
    def is_internal(self):
        """
        If this trajectory is contained within a single accounting system, 
        return ``True``, ``False`` otherwise.
        """
        return self.exit_point == None 

    @property
    def target_system(self):
        """
        The accounting system where this trajectory ends.
        """
        return self.entry_point.system
    
    @property
    def amount(self):
        """
        The amount of money flowing through this trajectory.
        """
        return self.target.amount
    
            
class Transaction(models.Model):
    """
    A transaction between accounts.
    
    From an abstract point of view, a transaction is just a set of flows of money
    occurring between two or more accounts belonging to one or more accounting system(s).
    
    As a data structure, a transaction can be modeled by a 2-tuple: 
    
    ``(source, trajectories)``
    
    where:
    * ``source`` is a ``CashFlow`` instance describing the source account 
      and the amount of money flowing from/to it
    * ``trajectories`` is a tuple of ``Trajectory`` instances describing the
      partial flows (a.k.a. *splits*) composing the transaction, and their
      paths through the accounting systems involved in the transaction.   
    
    So, a transaction can be defined as a collection of splits 
    sharing the same source account.
    
    A transaction is said to be: 
    - *simple* if the source and target accounts belong to the same accounting system
    - *split* if it comprises more than one trajectory (i.e., splits)
    
    Some facts deriving from these definitions:
    - simple transactions don't modify the total amount of money contained 
      within the (single) accounting system they operate on
    - on the other hand, non-simple transactions transfer money from/to an accounting system
      to/from one or more other accounting system(s)
    - the amount of money flowing from/to the source account equals the algebraic sum of those 
      flowing through the splits comprising the transaction (this descends from 
      the *law of conservation of money*)
    
    Furthermore, a transaction is characterized by some metadata:
    * the date when it happened
    * a reason for the transfer
    * who autorized the transaction
    * the type of the transaction 
     
    """   
    # when the transaction happened
    date = models.DateTimeField(default=datetime.now)
    # what the transaction represents
    description = models.CharField(max_length=512, help_text=_("Reason of the transaction"))
    # who triggered the transaction
    issuer = models.ForeignKey(Subject, related_name='issued_transactions_set')
    # source flows for this transaction
    source = models.ForeignKey(CashFlow)     
    # trajectory components
    component_set = models.ManyToManyField(Trajectory)
    # the type of this transaction
    kind = models.CharField(max_length=128, choices=settings.TRANSACTION_TYPES)
    
    def __unicode__(self):
        return _("%(kind)s issued by %(issuer)s at %(date)s") % {'kind' : self.kind, 'issuer' : self.issuer, 'date' : self.date}
    
    # model-level custom validation goes here
    def clean(self):
        # TODO: check that the *law of conservation of money* is satisfied
        # TODO: check that exit points belong to the same accounting system 
        # TODO: as the source account
        # TODO: for internal trajectories, check that target account belongs 
        # TODO: to the same accounting system as the source account
        pass
        
    def save(self, *args, **kwargs):
        # perform model validation
        self.full_clean()
        super(Transaction, self).save(*args, **kwargs)
        
    @property
    def components(self):
        return self.component_set.all()
    
        
    @property
    def is_split(self):
        """
        Return ``True if this transaction is a split one;
        ``False`` otherwise.
        """
        # a transaction is split iff it comprises more than one trajectory
        return len(self.components) > 1
    
    @property
    def is_simple(self):
        """
        Return ``True if this transaction is a simple one;
        ``False`` otherwise.
        """
        # a transaction is simple iff it's contained within a single accounting system
        simple = True
        for trajectory in self.components:
            if not trajectory.is_internal:
                simple = False                
        return simple   

class LedgerEntry(models.Model):
    """
    An entry in a ledger. 
    
    Every account within an accounting system is associated with a ledger
    (i.e. an accounting log) used for recording cash-flows related to that account.
    
    In turn, entries in a ledger are generated by transactions between different accounts 
    - either belonging to the same accounting system or to different ones.
    
    Given that:
    * a general transaction is composed of one or more trajectories sharing their starting
      point (the source account)
    * each trajectory may pass through multiple accounts (up to 3 of them)
    * a ledger entry is generated for each account "touched" by the transaction
    
    it follows that a single transaction generates multiple ledger entries, ranging from a 
    minimum of two (for internal, non-split transactions) to maximum of `3n + 1` (for n-split
    transactions with all-distinct entry/exit points).
    
    Note that the meaning of a ledger entry differs among stock-like and flux-like accounts:
    * for stock-like ones, an entry registers a *change* in the *amount* of money contained 
      within the account
    * for flux-like ones, an entry registers a flow *through* the account  
    """
    # each entry is written to the ledger associated with an account   
    account = models.ForeignKey(Account, related_name='entry_set')
    # each entry is generated by a transaction
    transaction = models.ForeignKey(Transaction, related_name='entry_set')
    # a serial number for this entry
    # note that the model's primary key is unsuitable for this purpose, 
    # since it's incremented at the model level (not on a per-ledger basis)
    entry_id = models.PositiveIntegerField(null=True, blank=True, editable=False)
    # the amount of money flowing 
    amount = CurrencyField()
    
    @property
    def date(self):
        return self.transaction.date
    
    @property
    def description(self):
        return self.transaction.description
    
    @property
    def issuer(self):
        return self.transaction.issuer
    
    
    def next_entry_id_for_ledger(self):
        """
        Get the first available integer to be used as an ID for this entry in the ledger.
        """
        existing_entries = self.account.ledger_entries
        next_id = max([entry.id for entry in existing_entries]) + 1
        return next_id
    
    def save(self, *args, **kwargs):
        # if this entry is saved to the DB for the first time,
        # set its ID in the ledger to the first available value
        if not self.pk:
            self.entry_id = self.next_entry_id_for_ledger() 
        super(LedgerEntry, self).save(*args, **kwargs)


    
class Invoice(models.Model):
    """
    An invoice document issued by a subject against another subject.
    
    This model contains metadata useful for invoice management, embodying the actual document as a ``FileField``. 
    
    These metadata can be used to link invoices with related accounting systems (i.e. those of issuer and recipient subjects);    
    for example, when an invoice is payed, the system could automatically create a transaction reflecting this action.     
    """
    # who issued the invoice
    issuer = models.ForeignKey(Subject, related_name='issued_invoice_set')
    # who have to pay for the invoice
    recipient = models.ForeignKey(Subject, related_name='received_invoice_set')
    # invoice's amount (excluding taxes)
    net_amount = CurrencyField()
    # taxes due for the invoice (VAT,..)
    taxes = CurrencyField(blank=True, null=True)
    # when the invoice has been issued
    issue_date = models.DateTimeField()
    # when the invoice is due
    due_date = models.DateTimeField()
    # Does this invoice has been payed ?
    is_payed = models.BooleanField(default=False)
    # FIXME: implement a more granular storage pattern
    document = models.FileField(upload_to='/invoices')
    
    def __unicode__(self):
        return _("Invoice issued by %(issuer)s to %(recipient)s on date %(issue_date)s"\
                 % {'issuer' : self.issuer, 'recipient' : self.recipient, 'issue_date' : self.issue_date} )
    
    @property
    def total_amount(self):
        """Total amount for the invoice (including taxes)."""
        return self.net_amount + self.taxes  

  
class AccountingProxy(object):
    """
    This class is meant to be used as a proxy for accessing accounting-related functionality.
    """
    
    def __init__(self, subject):
        self.subject = subject
        self.accounts = subject.accounting_system
    
    @property    
    def account(self):
        """
        Return the main account of the current subject (if any).
        
        Since the semantic of 'main account' is strongly domain-dependent, 
        actual implementation of this method is delegated to domain-specific subclasses.  
        """
        raise NotImplementedError
        
    def make_transactions_for_invoice_payment(self, invoice, is_being_payed):
        """
        Usually, the action of paying/collecting an invoice triggers one or more transactions 
        within one or more accounting systems;  on the other hand, details about these transaction(s) 
        are strictly domain-dependent, so this hook is provided for concrete subclasses 
        to override as needed.        
        """
        pass
    
    def pay_invoice(self, invoice):
        """
        Pay an invoice issued to the subject owning this accounting system.
        
        If ``invoice`` isn't an ``Invoice`` model instance, or if it was issued to another subject,
        raise ``ValueError``.   
        
        Usually, the action of paying an invoice triggers one or more transactions within one or more accounting systems; 
        on the other hand, details about these transaction(s) are strictly domain-dependent, so this method invokes
        the hook ``AccountingProxy.make_transactions_for_invoice_payment()`` that concrete subclasses should override. 
        """
        
        if isinstance(invoice, Invoice) and  invoice.recipient == self.subject:
            self.make_transactions_for_invoice_payment(invoice, is_being_payed=True)                      
            invoice.is_payed = True
        else: 
            # FIXME: provide a more informative error message
            raise ValueError
    
    def set_invoice_payed(self, invoice):
        """
        Mark as 'payed' an invoice issued by the subject owning this accounting system.
        
        If ``invoice`` isn't an ``Invoice`` model instance, or if it was issued by another subject,
        raise ``ValueError``.            
        
        Usually, the action of paying an invoice triggers one or more transactions within one or more accounting systems; 
        on the other hand, details about these transaction(s) are strictly domain-dependent, so this method invokes
        the hook ``AccountingProxy.make_transactions_for_invoice_payment()`` that concrete subclasses should override.
        """
        
        if isinstance(invoice, Invoice) and  invoice.issuer == self.subject:
            self.make_transactions_for_invoice_payment(invoice, is_being_payed=False)                      
            invoice.is_payed = True
        else: 
            # FIXME: provide a more informative error message
            raise ValueError    
        
class AccountingDescriptor(object):
    """
    """
    # TODO: provide more detailed error messages
    # (maybe using ``contribute_to_class()`` Django hook to store 
    # the attribute name this descriptor was given)
    def __init__(self, proxy_class=AccountingProxy):
        self.proxy_class = proxy_class
    
    def __get__(self, instance, owner):
        
        if instance is None:
            raise AttributeError("This attribute can only be accessed from a %s instance" % owner.__name__)
        
        from accounting.utils import get_subject_from_subjective_instance
        # retrieve the ``Subject`` instance bound to this model instance
        subject = get_subject_from_subjective_instance(instance)
        # instantiate the proxy class for accessing accounting functionality for this instance
        # and return it to the caller instance
        return self.proxy_class(subject)
    
    def __set__(self, instance, value):
        raise AttributeError("This is a read-only attribute")
