from django.contrib.auth.models import User
from rest_framework.test import APITestCase
from user.models import User
from django.test import Client
from competition.forms import ProfileUpdateForm
from user.forms import UserChangeForm, NameUpdateForm
from personal.models import County, District, School, Profile
from personal.serializers import ProfileSerializer

class UpdateUserTest(APITestCase):
    def test_user_change_form(self):
        form = UserChangeForm(data = {
            'email': 'ja@strom.sk',
            'password': 'Aa123456'
        })
        self.assertTrue(form.is_valid())

    def test_wrong_email(self):
        form = UserChangeForm(data = {
            'email': '123',
            'password': 'Aa123456'
        })
        self.assertFalse(form.is_valid())

    def test_name_change_form(self):
        form = NameUpdateForm(data = {
            'first_name': 'Jožko',
            'last_name': 'Mrkvička'
        })
        self.assertTrue(form.is_valid())

    def test_profile_update_form(self):
        form = ProfileUpdateForm(data = {
            'first_name':'Účastník', 
            'last_name':'Matikovský', 
            'user' : {
                'email':'ucastnici@gmail.com', 'password':'1234abcd'
            }, 
            'nickname' : 'ucastnik', 
            'school' : {
                'name' : 'Gymnázium',
                'district' : {
                    'name' : 'Košice I',
                    'county': {'name' : 'Košický kraj'}
                },
                'street' : 'Poštová 9', 
                'city': 'Košice', 
                'zip_code' : '04001'
            }, 'year_of_graduation': 2025, 
            'phone' : '+421901234567', 
            'parent_phone' : '+421987654321', 
            'gdpr' : True
        })

        self.assertTrue(form.is_valid())

    def setUp(self):
        self.client = Client()
        user = User.objects.create(email="ucastnici@gmail.com", password="1234abcd")

        county = County.objects.create(name="Košický kraj")
        district = District.objects.create(name="Košice I", county=county)
        school = School.objects.create(name='Gymnázium', district=district, street='Poštová 9', city='Košice', zip_code='04001') 

        self.profile = Profile.objects.create(
            first_name='Účastník', last_name='Matikovský', user = user, 
            nickname = 'ucastnik', school = school, year_of_graduation = 2025, 
            phone = '+421901234567', parent_phone = '+421987654321', gdpr = True
        )

        #self.superuser = User.objects.create_superuser('veduci','1234abcd')
        #self.veduci_log_in = {'username':'veduci', 'password':'1234abcd'}
        #self.client.post('/user/login/',self.veduci_log_in)

        self.profiledata = ProfileSerializer(self.profile)
        self.userdata = {
            'first_name': 'Účastník',
            'last_name': 'Matikovský'
        }

        self.profiledata.update({'first_name': 'Meno', 'last_name': 'Priezvisko'})
        self.userdata.update({'first_name': 'Meno', 'last_name': 'Priezvisko'})

        self.data = {
            'user' : self.userdata,
            'profile' : self.profiledata
        }

        self.log_in = {'nickname':'ucastnik', 'password':'1234abcd'}

    def test_can_update_profile(self):
        response_log_in = self.client.post('/user/login/',self.log_in)
        self.assertEqual(response_log_in.status_code,200)
        response = self.client.post('/user/profile/update/', self.data)
        self.assertEqual(response.status_code, 200)
