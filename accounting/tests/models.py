from django.db import models

from accounting.fields import CurrencyField
from accounting.models import AccountType, Account
from accounting.models import AccountingProxy, economic_subject

## People
@economic_subject
class Person(models.Model):
    name = models.CharField(max_length=128)
    surname = models.CharField(max_length=128)
    
    @property
    def full_name(self):
        return self.name + self.surname
    
    def setup_accounting(self):
        self.subject.init_accounting_system()
        system = self.accounting_system
        # create a generic asset-type account (a sort of "virtual wallet")
        asset_type = AccountType.objects.get(name='ASSET')
        system.add_account(parent=system.root, name='wallet', kind=asset_type)  
    
    def save(self, *args, **kwargs):
        # run only at instance creation-time 
        if not self.pk:
            self.setup_accounting() 
        super(Person, self).save(*args, **kwargs)

    
## GASs
@economic_subject
class GAS(models.Model):
    name = models.CharField(max_length=128, unique=True)

    def setup_accounting(self):
        self.subject.init_accounting_system()
        system = self.accounting_system
        asset_type = AccountType.objects.get(name='ASSET')
        income_type = AccountType.objects.get(name='INCOME')
        expense_type = AccountType.objects.get(name='EXPENSE')
        ## setup a base account hierarchy
        # GAS's cash       
        system.add_account(parent=system.root, name='cash', kind=asset_type) 
        # root for GAS members' accounts 
        system.add_account(parent=system.root, name='members', kind=asset_type, placeholder=True)
        # a placeholder for organizing transactions representing payments to suppliers
        system.add_account(parent=system['/expenses'], name='suppliers', kind=expense_type, placeholder=True)
        # recharges made by GAS members to their own account
        system.add_account(parent=system['/incomes'], name='recharges', kind=income_type)
        # membership fees
        system.add_account(parent=system['/incomes'], name='fees', kind=income_type)
        
    def save(self, *args, **kwargs):
        # run only at instance creation-time 
        if not self.pk:
            self.setup_accounting() 
        super(GAS, self).save(*args, **kwargs)


class GASMember(models.Model):
    person = models.ForeignKey(Person)
    gas = models.ForeignKey(GAS)
    
    def setup_accounting(self):
        person_system = self.person.subject.accounting_system
        gas_system = self.gas.subject.accounting_system
        
        asset_type = AccountType.objects.get(name='ASSET')
        expense_type = AccountType.objects.get(name='EXPENSE')
        ## account creation
        ## Person-side
        try:
            base_account = person_system['/expenses/gas'] 
        except Account.DoesNotExist:
            person_system.add_account(parent=person_system['/expenses'], name='gas', kind=expense_type, placeholder=True)
        # placeholder for payments made to the GAS
        person_system.add_account(parent=base_account, name=str(self.gas.name), kind=expense_type, placeholder=True)
        # recharges
        person_system.add_account(parent=person_system['/expenses/' + str(self.gas.name)], name='recharges', kind=expense_type)
        # membership fees
        person_system.add_account(parent=person_system['/expenses/' + str(self.gas.name)], name='fees', kind=expense_type)
        ## GAS-side   
        gas_system.add_account(parent=gas_system['/members'], name=str(self.person.full_name), kind=asset_type)
    
    def save(self, *args, **kwargs):
        # run only at instance creation-time 
        if not self.pk:
            self.setup_accounting() 
        super(GASMember, self).save(*args, **kwargs)
    
## Suppliers     
@economic_subject              
class Supplier(models.Model):
    name = models.CharField(max_length=128, unique=True)
    
    def setup_accounting(self):
        self.subject.init_accounting_system()
        system = self.accounting_system
        asset_type = AccountType.objects.get(name='ASSET')
        income_type = AccountType.objects.get(name='INCOME')
        ## setup a base account hierarchy   
        # a generic asset-type account (a sort of "virtual wallet")        
        system.add_account(parent=system.root, name='wallet', kind=asset_type)  
        # a placeholder for organizing transactions representing GAS payments
        system.add_account(parent=system['/incomes'], name='gas', kind=income_type, placeholder=True)
        
    def save(self, *args, **kwargs):
        # run only at instance creation-time 
        if not self.pk:
            self.setup_accounting() 
        super(Supplier, self).save(*args, **kwargs)


class Product(models.Model):
    name = models.CharField(max_length=128)
     

class SupplierStock(models.Model):
    supplier = models.ForeignKey(Supplier, related_name='stock_set')
    product = models.ForeignKey(Product, related_name='stock_set')
    price = CurrencyField()
     
## GAS-Supplier interface
class GASSupplierSolidalPact(models.Model):
    gas = models.ForeignKey(GAS, related_name='pact_set')
    supplier = models.ForeignKey(Supplier, related_name='pact_set')
    
    def setup_accounting(self):
        ## create accounts for logging GAS <-> Supplier transactions
        income_type = AccountType.objects.get(name='INCOME')
        expense_type = AccountType.objects.get(name='EXPENSE')
        # GAS-side
        gas_system = self.gas.subject.accounting_system
        gas_system.add_account(parent=gas_system['/expenses/suppliers'], name=str(self.supplier.name), kind=expense_type)
        # Supplier-side
        supplier_system = self.supplier.subject.accounting_system
        supplier_system.add_account(parent=supplier_system['/incomes/gas'], name=str(self.gas.name), kind=income_type)
    
    def save(self, *args, **kwargs):
        # run only at instance creation-time 
        if not self.pk:
            self.setup_accounting() 
        super(GASSupplierSolidalPact, self).save(*args, **kwargs)

## Orders
# GAS -> Supplier   
class GASSupplierStock(models.Model):
    pact = models.ForeignKey(GASSupplierSolidalPact)
    stock = models.ForeignKey(SupplierStock)  
    

class GASSupplierOrder(models.Model):
    pact = models.ForeignKey(GASSupplierSolidalPact, related_name='order_set')
    

class GASSupplierOrderProduct(models.Model):
    order = models.ForeignKey(GASSupplierOrder)
    gas_stock = models.ForeignKey(GASSupplierStock)
    # the price of the Product at the time the GASSupplierOrder was created
    initial_price = CurrencyField()
    # the price of the Product at the time the GASSupplierOrder was sent to the Supplier
    order_price = CurrencyField()
    # the actual price of the Product (as resulting from the invoice)
    delivered_price = CurrencyField(null=True, blank=True)
    # how many items were actually delivered by the Supplier 
    delivered_amount = models.PositiveIntegerField(null=True, blank=True)
    
# GAS member -> GAS
class GASMemberOrder(models.Model):
    purchaser = models.ForeignKey(GASMember)
    ordered_product = models.ForeignKey(GASSupplierOrderProduct)
    # price of the Product at order time
    ordered_price = CurrencyField()
    # how many Product units were ordered by the GAS member
    ordered_amount = models.PositiveIntegerField()
    # how many Product units were withdrawn by the GAS member 
    withdrawn_amount = models.PositiveIntegerField()

#--------------------------- Accounting proxy-classes --------------------------#

class PersonAccountingProxy(AccountingProxy):
    """
    WRITEME
    """
    pass

class GasAccountingProxy(AccountingProxy):
    """
    WRITEME
    """
    pass

class SupplierAccountingProxy(AccountingProxy):
    """
    WRITEME
    """
    pass

