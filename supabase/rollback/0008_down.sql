grant insert on public.projects to authenticated;
create policy "projects_insert_admin" on public.projects for insert with check (private.is_org_member(organization_id, 'admin'));

drop function if exists public.export_my_data();
drop function if exists public.delete_my_account();
drop function if exists public.create_project(text);
