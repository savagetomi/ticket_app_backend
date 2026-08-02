from django.contrib.auth.base_user import BaseUserManager

class UserManager(BaseUserManager):
    def create_user(self, first_name, last_name, email_address, phone_number,password=None, **extra_fields):
        if not email_address:
            raise "Email Address invalid"
        if not phone_number:
            raise "Please input a right phone number"
        
        self.normalize_email(email_address)
        user=self.model(
            email_adress=email_address,
            phone_number=phone_number,
            first_name=first_name,
            last_name=last_name,
            **extra_fields
        )

        user.set_password(password)
        user.save(using=self._db)
        return user
    
    def create_superuser(self, first_name, last_name, email_address, phone_number,password=None,**extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_verified", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("phone_verified", True)
        extra_fields.setdefault("role", "Admin")

        if extra_fields.get("is_staff") is not True:
            raise ValueError ("SuperUser must have is_staff=True")
        if extra_fields.get("phone_verified") is not True:
            raise ValueError ("SuperUser must have phone_verified=True")
        
        return self.create_user(phone_number, email, password, **extra_fields)
    
    def get_by_natural_key(self, username):
        return self.get(**{f'{self.model.USERNAME_FIELD}__iexact': username})